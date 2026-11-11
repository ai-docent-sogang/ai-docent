// 아이폰 Safari에서 Live API 음성 왕복이 되는지 확인하는 시험 페이지의 동작.
//
// 담당: FE1
// 같이 보는 파일: live_test.html (화면), live_mic_worklet.js (마이크 16kHz), live_player.js (24kHz 재생),
//               tools/live_relay_spike.py (중계 서버), docs/FE1_Live_검토.md
//
// 이 페이지는 Live 전환 가능 여부를 가리기 위한 '시험'이다. 운영 화면이 아니다.
// 확인하려는 것 네 가지:
//   ① 아이폰 Safari에서 AudioWorklet으로 마이크를 16kHz PCM으로 뽑을 수 있는가
//   ② 받은 24kHz 생 PCM을 끊김 없이 재생할 수 있는가
//   ③ 말이 끝난 뒤 첫 소리까지 실제로 몇 초인가 (맥에서는 950ms였다)
//   ④ 받아쓰기가 실제 사람 목소리에도 맞는가 (맥에서는 합성음으로만 확인했다)
//
// 화면에 뜨는 값은 모두 측정값이거나 브라우저가 알려 준 값이다. 추정해서 쓰지 않는다.

import { ARTWORKS, DEFAULT_ARTWORK_ID } from "./config.js";
import { createPlayer } from "./live_player.js";

const $ = (id) => document.getElementById(id);
const player = createPlayer();

let socket = null;
let micStream = null;
let micCtx = null;
let workletNode = null;
let speaking = false; // 마이크를 보내는 중인가

// 측정값
let spokeEndedAt = null; // 말이 끝났다고 누른 시각
let firstAudioMs = null; // 그 뒤 첫 소리까지
let bytesSent = 0;
let bytesReceived = 0;

function log(text, kind = "") {
  const line = document.createElement("div");
  line.className = `line ${kind}`;
  line.textContent = `${new Date().toLocaleTimeString()}  ${text}`;
  $("log").prepend(line);
}

function setStatus(text) { $("status").textContent = text; }

function showMetrics() {
  $("metrics").textContent = [
    `마이크 ${micCtx ? micCtx.sampleRate : "-"} Hz → 16000 Hz`,
    `재생 ${player.sampleRate || "-"} Hz (받은 PCM 24000 Hz)`,
    `보냄 ${(bytesSent / 1024).toFixed(0)} KB · 받음 ${(bytesReceived / 1024).toFixed(0)} KB`,
    firstAudioMs === null ? "첫 소리 미측정" : `말 끝난 뒤 첫 소리 ${firstAudioMs} ms`,
    `재생 대기 ${player.queued}`,
  ].join(" · ");
}
setInterval(showMetrics, 500);

// 작품 목록 채우기
for (const art of ARTWORKS) {
  const option = document.createElement("option");
  option.value = art.id;
  option.textContent = art.label;
  $("artwork").appendChild(option);
}
$("artwork").value = DEFAULT_ARTWORK_ID;

// ① 연결: AudioContext와 마이크를 사용자 조작 안에서 준비한다(아이폰 필수).
$("connect").addEventListener("click", async () => {
  $("connect").disabled = true;
  try {
    // 먼저 소리 쪽을 깨운다. await 뒤로 밀면 아이폰이 재생을 막는다(audio.js에서 겪은 문제).
    const playerInfo = await player.start();
    log(`재생 준비: ${playerInfo.sampleRate} Hz, ${playerInfo.state}`, "ok");

    if (!window.AudioWorklet) throw new Error("이 브라우저에 AudioWorklet이 없습니다");

    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
    micCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (micCtx.state === "suspended") await micCtx.resume();
    await micCtx.audioWorklet.addModule("/static/live_mic_worklet.js");
    log(`마이크 준비: ${micCtx.sampleRate} Hz`, "ok");

    workletNode = new AudioWorkletNode(micCtx, "mic-downsampler");
    workletNode.port.onmessage = (event) => {
      // 말하는 중일 때만 보낸다. 버튼을 누르지 않았으면 소리를 버린다(필요 없는 전송을 막는다).
      if (!speaking || !socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(event.data.buffer);
      bytesSent += event.data.byteLength;
    };
    micCtx.createMediaStreamSource(micStream).connect(workletNode);
    // 아이폰에서 AudioWorklet이 멈추지 않도록 destination에 붙인다. 소리는 내보내지 않는다.
    const silent = micCtx.createGain();
    silent.gain.value = 0;
    workletNode.connect(silent).connect(micCtx.destination);

    await openSocket();
  } catch (err) {
    $("connect").disabled = false;
    setStatus(`준비 실패: ${err.message}`);
    log(`준비 실패: ${err.name || ""} ${err.message}`, "err");
  }
});

function openSocket() {
  return new Promise((resolve, reject) => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}/ws/live`);
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      socket.send(JSON.stringify({ artwork_id: $("artwork").value }));
      log("WebSocket 열림", "ok");
    };
    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        if (firstAudioMs === null && spokeEndedAt !== null) {
          firstAudioMs = Math.round(performance.now() - spokeEndedAt);
          log(`첫 소리까지 ${firstAudioMs} ms`, "ok");
        }
        bytesReceived += event.data.byteLength;
        player.push(event.data);
        return;
      }
      const data = JSON.parse(event.data);
      if (data.type === "ready") {
        setStatus(`연결됨 · ${data.model} · ${data.artwork_title}`);
        $("talk").disabled = false;
        log(`서버 준비: ${data.model}`, "ok");
        resolve();
      } else if (data.type === "heard") {
        $("heard").textContent += data.text;
      } else if (data.type === "said") {
        $("said").textContent += data.text;
      } else if (data.type === "turn_complete") {
        log("답변 끝", "ok");
        setStatus("말하기 버튼으로 다시 물어보세요.");
      } else if (data.type === "error") {
        log(`서버 오류: ${data.message}`, "err");
        reject(new Error(data.message));
      }
    };
    socket.onerror = () => log("WebSocket 오류", "err");
    socket.onclose = (event) => {
      log(`WebSocket 닫힘 (code ${event.code})`, "err");
      setStatus("연결이 끊겼습니다. 페이지를 새로 열어 다시 시도하세요.");
      $("talk").disabled = true;
    };
  });
}

// ② 말하기: 누르고 있는 동안 마이크를 보낸다. 떼면 끝을 알린다.
const talkBtn = $("talk");

talkBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  player.stop(); // 답변이 나오는 중이면 멈춘다(마이크가 그 소리를 되받지 않게)
  speaking = true;
  firstAudioMs = null;
  spokeEndedAt = null;
  $("heard").textContent = "";
  $("said").textContent = "";
  talkBtn.classList.add("recording");
  talkBtn.textContent = "듣는 중… 떼면 보냄";
  setStatus("말하세요.");
});

["pointerup", "pointercancel", "pointerleave"].forEach((type) =>
  talkBtn.addEventListener(type, () => {
    if (!speaking) return;
    speaking = false;
    spokeEndedAt = performance.now(); // 체감 지연의 시작점
    socket.send(JSON.stringify({ type: "audio_end" }));
    talkBtn.classList.remove("recording");
    talkBtn.textContent = "누르고 말하기";
    setStatus("답을 기다립니다…");
    log("말 끝. 서버에 알림", "");
  })
);

// 재생만 따로 확인하는 버튼. 마이크 없이 소리가 나오는지 가린다.
$("tone").addEventListener("click", async () => {
  await player.start();
  // 24kHz로 0.4초짜리 440Hz 소리를 만들어 넣는다. 재생 경로만 시험한다.
  const samples = new Int16Array(24000 * 0.4);
  for (let i = 0; i < samples.length; i++) {
    samples[i] = Math.sin((2 * Math.PI * 440 * i) / 24000) * 0x3fff;
  }
  player.push(samples.buffer);
  log("시험음 재생(440Hz 0.4초). 들리지 않으면 재생 경로 문제", "");
});

$("stop").addEventListener("click", () => {
  player.stop();
  log("재생 멈춤", "");
});

log(`브라우저: AudioWorklet ${window.AudioWorklet ? "있음" : "없음"} · WebSocket ${window.WebSocket ? "있음" : "없음"}`);
