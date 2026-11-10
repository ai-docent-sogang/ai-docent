// AI 도슨트 폰 웹앱의 화면 흐름: 카메라 켜기 → 버튼 누르고 말하기 → 사진 한 장 찍기 → 서버로 보내기 → 답 읽어 주기.
//
// 담당: FE1
// 같이 보는 파일: audio.js (WAV 변환·음성 출력), api.js (서버 요청), index.html (화면 요소), docs/api.md
//
// 녹음과 사진은 서버로 보내기만 하고 기기에 저장하지 않는다.
// 아이폰 Safari는 https:// 주소에서만 카메라·마이크를 허용한다(README의 Cloudflare 터널 참고).

import { postAsk, postTurn, startSession } from "./api.js";
import { ARTWORKS, DEFAULT_ARTWORK_ID } from "./config.js";
import { isSupported as sttSupported, listen, stopListening } from "./stt.js";
import { initAudio, speak, stopSpeaking, toWav16k } from "./audio.js";

// 이 파일은 흐름이 둘이다. 서로 건드리지 않는다.
//   ① /api/turn  — 녹음 + 사진 + 세션 기억. 11/4 시연부터 쓰던 흐름.
//   ② /api/ask   — 고른 작품 1점 + 질문 텍스트. 11/11 BE1이 추가(docs/api.md).
// ②를 시험하는 동안에도 ①은 그대로 동작해야 한다.

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

let lastReply = "";

function readReply(text) {
  $("audio-status").textContent = "Preparing voice… If silent, tap Replay reply.";
  speak(text, {
    onStart: () => { $("audio-status").textContent = "Speaking…"; },
    onEnd: () => { $("audio-status").textContent = "Voice finished."; },
    onError: (code) => {
      $("audio-status").textContent = `Voice error: ${code}. Tap Replay reply or Test voice. If still silent, check volume and audio output.`;
    },
  });
}

function rememberReply(text) {
  lastReply = text;
  $("replay").disabled = !text;
  readReply(text);
}

$("test-voice").addEventListener("click", () => readReply("Hello. This is the AI docent voice test."));
$("replay").addEventListener("click", () => { if (!busy && lastReply) readReply(lastReply); });

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
    await initAudio();
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } }, // 후면 카메라
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    video.srcObject = stream;
    const data = await startSession();
    sessionId = data.session_id;
    addMessage("docent", data.reply);
    rememberReply(data.reply);
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
  $("audio-status").textContent = "Voice stopped for recording.";
  $("replay").disabled = true;
  $("test-voice").disabled = true;
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
  $("replay").disabled = !lastReply;
  $("test-voice").disabled = false;
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
  stopSpeaking();
  $("replay").disabled = true;
  $("test-voice").disabled = true;
  talkBtn.disabled = true;
  setStatus("Thinking…");
  const t0 = performance.now();
  try {
    const data = await postTurn({ sessionId, audio, text, frame });
    addMessage("visitor", data.transcript || text);
    addMessage("docent", data.reply);
    rememberReply(data.reply);
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
    $("replay").disabled = !lastReply;
    $("test-voice").disabled = false;
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

// ===== ② 텍스트 전용 질문·답변(/api/ask) =====
// 작품을 직접 고르고 질문 텍스트만 보낸다. 세션·카메라·녹음을 쓰지 않으므로 Start 없이도 쓸 수 있다.
// 브라우저 음성 인식(STT)은 아직 없다. 지금은 글로 입력하고, 답변만 음성으로 읽어 준다.

// 작품 고르는 목록을 config.js의 ARTWORKS로 채운다.
const askArtwork = $("ask-artwork");
for (const art of ARTWORKS) {
  const option = document.createElement("option");
  option.value = art.id;
  option.textContent = art.label;
  askArtwork.appendChild(option);
}
askArtwork.value = DEFAULT_ARTWORK_ID;

// status 값마다 화면 아래에 덧붙일 안내. 관람객에게는 answer를 읽어 주고, 개발용 정보는 ask-meta에 둔다.
const ASK_STATUS_NOTE = {
  ok: "",
  mock: "임시 답변(ASK_MOCK=1). Gemini를 부르지 않았다.",
  no_artwork: "서버에 이 작품 자료가 없다.",
  error: "서버가 답변을 만들지 못했다. 서버 터미널의 [/api/ask] 줄을 확인한다.",
};

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("ask-input").value.trim();
  if (!question || busy) return;
  const artworkId = askArtwork.value;

  busy = true;
  $("ask-send").disabled = true;
  stopSpeaking();
  $("replay").disabled = true;
  $("test-voice").disabled = true;
  $("ask-meta").textContent = "Asking…";
  addMessage("visitor", question);
  $("ask-input").value = "";

  const t0 = performance.now();
  try {
    const data = await postAsk({ artworkId, question });
    addMessage("docent", data.answer);
    rememberReply(data.answer); // 화면에 쓰고 음성으로 읽어 준다(①과 같은 경로)
    const total = Math.round(performance.now() - t0); // 보내기부터 받기까지 왕복 시간
    const parts = [
      `ask: ${data.artwork_title || data.artwork_id}`,
      `status ${data.status}`,
      `server ${data.latency_ms} ms · total ${total} ms`,
    ];
    if (data.model) parts.push(`model ${data.model}`);
    $("ask-meta").textContent = parts.join(" · ");
    const note = ASK_STATUS_NOTE[data.status];
    if (note) $("ask-meta").textContent += ` — ${note}`;
    if (data.source_url) {
      // 출처는 관람객에게도 보여야 한다(AGENTS.md: 출처 있는 근거만 쓴다).
      const link = document.createElement("a");
      link.href = data.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "source";
      $("ask-meta").append(" · ", link);
    }
  } catch (err) {
    // 400(빈 질문)이나 서버에 닿지 못한 경우. 이때는 읽어 줄 문장이 없다.
    $("ask-meta").textContent = `Error: ${err.message}`;
  } finally {
    busy = false;
    $("ask-send").disabled = false;
    $("replay").disabled = !lastReply;
    $("test-voice").disabled = false;
  }
});

// ===== ③ 브라우저 음성 인식(STT)으로 질문 입력 =====
// 말한 내용을 질문 입력창에 넣는다. 보내기는 기존 ask-form 흐름을 그대로 쓴다.
// 브라우저가 지원하지 않으면 버튼을 끄고 글로 입력하게 안내한다(기능이 사라지지 않게).
// 주의: 브라우저 STT는 소리를 브라우저 회사 서버로 보낸다(stt.js 머리말 참고).

const listenBtn = $("ask-listen");
const sttStatus = $("ask-stt-status");
let listening = false;

// 오류 코드별 안내. 관람객이 다음에 무엇을 할지 알 수 있게 쓴다.
const STT_ERROR_NOTE = {
  unsupported: "This browser cannot listen. Please type your question.",
  "not-allowed": "Microphone blocked. Allow it in settings, or type your question.",
  "service-not-allowed": "Microphone blocked. Allow it in settings, or type your question.",
  "no-speech": "I did not catch that. Try again, or type your question.",
  network: "Speech recognition needs a network connection. Please type your question.",
  "audio-capture": "No microphone found. Please type your question.",
};

function setListening(on) {
  listening = on;
  listenBtn.classList.toggle("listening", on);
  listenBtn.textContent = on ? "Listening… tap to stop" : "Speak question";
}

if (!sttSupported()) {
  listenBtn.disabled = true;
  sttStatus.textContent = "Voice input not available. Type your question.";
}

listenBtn.addEventListener("click", () => {
  if (listening) { stopListening(); return; } // 한 번 더 누르면 멈춘다
  if (busy) return;
  stopSpeaking(); // 도슨트가 말하는 중이면 멈춘다(마이크가 자기 목소리를 듣지 않게)
  $("ask-input").value = "";
  $("ask-input").classList.remove("partial");
  sttStatus.textContent = "Listening…";
  setListening(true);
  listen({
    onPartial: (text) => {
      // 말하는 중간 결과는 흐리게 보여 준다. 최종 결과가 오면 덮어쓴다.
      $("ask-input").value = text;
      $("ask-input").classList.add("partial");
    },
    onFinal: (text) => {
      $("ask-input").value = text;
      $("ask-input").classList.remove("partial");
      sttStatus.textContent = "Check the question, then tap Ask.";
    },
    onError: (code) => {
      $("ask-input").classList.remove("partial");
      sttStatus.textContent = STT_ERROR_NOTE[code] || `Voice input error: ${code}. Please type your question.`;
      // 규격대로라면 오류 뒤에 onEnd가 따라오지만, 그렇지 않은 브라우저에서 버튼이
      // "듣는 중"으로 멈춰 있지 않게 여기서도 되돌린다. 두 번 불려도 문제 없다.
      setListening(false);
    },
    onEnd: () => setListening(false),
  });
});
