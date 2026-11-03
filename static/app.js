// AI 도슨트 폰 웹앱의 화면 흐름: 카메라 켜기 → 버튼 누르고 말하기 → 사진 한 장 찍기 → 서버로 보내기 → 답 읽어 주기.
//
// 담당: FE1
// 같이 보는 파일: audio.js (WAV 변환·음성 출력), api.js (서버 요청), index.html (화면 요소), docs/api.md
//
// 녹음과 사진은 서버로 보내기만 하고 기기에 저장하지 않는다.
// 아이폰 Safari는 https:// 주소에서만 카메라·마이크를 허용한다(README의 Cloudflare 터널 참고).

import { postTurn, startSession } from "./api.js";
import { initAudio, speak, stopSpeaking, toWav16k } from "./audio.js";

const $ = (id) => document.getElementById(id);
const video = $("camera");
const talkBtn = $("talk");

// 화면 전체가 공유하는 상태
let sessionId = null; // 서버가 준 관람 세션 ID
let stream = null; // 카메라·마이크 스트림
let recorder = null; // 녹음기(MediaRecorder)
let chunks = []; // 녹음 중 조금씩 들어오는 소리 조각
let busy = false; // 서버 답을 기다리는 중이면 true (중복 전송 방지)

// 녹음이 이보다 작으면 버튼을 너무 짧게 누른 것으로 보고 보내지 않는다(16kHz WAV 기준 약 0.25초).
const MIN_WAV_BYTES = 8000;
// 서버로 보내는 사진의 최대 가로 크기. 크면 인식에는 유리하지만 전송과 응답이 느려진다.
const FRAME_MAX_WIDTH = 768;

function setStatus(text) { $("status").textContent = text; }

// 대화 기록 창에 말풍선 하나를 추가한다. who: "visitor" 또는 "docent"
function addMessage(who, text) {
  if (!text) return;
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}

// ① Start: 카메라·마이크를 켜고 세션을 시작한 뒤 첫 인사를 읽는다.
$("start").addEventListener("click", async () => {
  $("start").disabled = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } }, // 후면 카메라
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    video.srcObject = stream;
    initAudio(); // iOS: 탭 직후에 소리 기능을 열어 둬야 한다
    const data = await startSession();
    sessionId = data.session_id;
    addMessage("docent", data.reply);
    speak(data.reply);
    talkBtn.disabled = false;
    setStatus("Point the camera at a painting and hold the red button to talk.");
  } catch (err) {
    $("start").disabled = false;
    setStatus(`Could not start: ${err.message}`);
  }
});

// ② 버튼을 누르는 순간 녹음을 시작한다. 도슨트가 말하던 중이면 멈춘다.
talkBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (busy || !stream) return;
  stopSpeaking();
  chunks = [];
  recorder = new MediaRecorder(new MediaStream(stream.getAudioTracks())); // 카메라는 빼고 마이크만 녹음
  recorder.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
  recorder.onstop = onRecordingStop;
  recorder.start();
  talkBtn.classList.add("recording");
  talkBtn.textContent = "Listening… release to send";
});

// ③ 버튼에서 손을 떼거나, 손가락이 버튼 밖으로 나가거나, 터치가 취소되면 녹음을 끝낸다.
["pointerup", "pointercancel", "pointerleave"].forEach((type) =>
  talkBtn.addEventListener(type, () => {
    if (recorder && recorder.state === "recording") recorder.stop(); // → onRecordingStop 실행
    talkBtn.classList.remove("recording");
    talkBtn.textContent = "Hold to talk";
  })
);

// ④ 녹음이 끝나면 사진을 찍고, 녹음을 WAV로 바꿔 보낸다.
async function onRecordingStop() {
  const blob = new Blob(chunks, { type: recorder.mimeType });
  const frame = await captureFrame();
  let wav;
  try {
    wav = await toWav16k(blob);
  } catch (err) {
    setStatus(`Could not read the recording: ${err.message}`);
    return;
  }
  if (wav.size < MIN_WAV_BYTES) { setStatus("Too short. Hold the button while you speak."); return; }
  await sendTurn({ audio: wav, frame });
}

// 말하기 어려운 환경을 위한 글 입력. 녹음 대신 글을 보낸다.
$("text-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !sessionId || busy) return;
  $("text-input").value = "";
  await sendTurn({ text, frame: await captureFrame() });
});

// ⑤ 서버로 보내고, 답을 화면에 쓰고, 읽어 준다. 하단에 인식 결과와 응답 시간을 표시한다.
async function sendTurn({ audio, text, frame }) {
  busy = true;
  talkBtn.disabled = true;
  setStatus("Thinking…");
  const t0 = performance.now();
  try {
    const data = await postTurn({ sessionId, audio, text, frame });
    addMessage("visitor", data.transcript || text);
    addMessage("docent", data.reply);
    speak(data.reply);
    const total = Math.round(performance.now() - t0); // 보내기 시작부터 답을 받기까지 전체 시간
    $("meta").textContent =
      `artwork: ${data.artwork_title || data.artwork_id} · comparison: ${data.comparison_id || "-"} · ` +
      `profile: ${data.profile.country || "?"} / ${data.profile.familiar_art.join(", ") || "?"} · ` +
      `gemini ${data.latency_ms} ms · total ${total} ms`;
    setStatus("Hold the red button to ask more.");
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  } finally {
    busy = false;
    talkBtn.disabled = false;
  }
}

// 카메라 화면에서 지금 순간을 JPEG 한 장으로 찍는다. 카메라가 아직 준비되지 않았으면 null.
function captureFrame() {
  if (!video.videoWidth) return Promise.resolve(null);
  const scale = Math.min(1, FRAME_MAX_WIDTH / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.75)); // 0.75 = JPEG 화질
}
