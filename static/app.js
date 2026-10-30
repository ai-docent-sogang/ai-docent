// AI 도슨트 v0 폰 클라이언트: 카메라 미리보기, 누르고 말하기, 프레임 캡처, 영어 음성 출력.
// 녹음과 프레임은 서버로 보내기만 하고 기기에 저장하지 않는다.

const $ = (id) => document.getElementById(id);
const video = $("camera");
const talkBtn = $("talk");
let sessionId = null;
let stream = null;
let audioCtx = null;
let recorder = null;
let chunks = [];
let busy = false;

function setStatus(text) { $("status").textContent = text; }

function addMessage(who, text) {
  if (!text) return;
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}

function speak(text) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  const voice = speechSynthesis.getVoices().find((v) => v.lang === "en-US");
  if (voice) u.voice = voice;
  speechSynthesis.speak(u);
}

$("start").addEventListener("click", async () => {
  $("start").disabled = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    video.srcObject = stream;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    speak(""); // iOS: 사용자 탭 안에서 음성 출력을 한 번 열어 둔다.
    const res = await fetch("/api/session", { method: "POST" });
    const data = await res.json();
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

talkBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (busy || !stream) return;
  speechSynthesis.cancel();
  chunks = [];
  recorder = new MediaRecorder(new MediaStream(stream.getAudioTracks()));
  recorder.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
  recorder.onstop = onRecordingStop;
  recorder.start();
  talkBtn.classList.add("recording");
  talkBtn.textContent = "Listening… release to send";
});

["pointerup", "pointercancel", "pointerleave"].forEach((type) =>
  talkBtn.addEventListener(type, () => {
    if (recorder && recorder.state === "recording") recorder.stop();
    talkBtn.classList.remove("recording");
    talkBtn.textContent = "Hold to talk";
  })
);

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
  if (wav.size < 8000) { setStatus("Too short. Hold the button while you speak."); return; }
  await sendTurn({ audio: wav, frame });
}

$("text-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !sessionId || busy) return;
  $("text-input").value = "";
  await sendTurn({ text, frame: await captureFrame() });
});

async function sendTurn({ audio, text, frame }) {
  busy = true;
  talkBtn.disabled = true;
  setStatus("Thinking…");
  const form = new FormData();
  form.append("session_id", sessionId);
  if (text) form.append("text", text);
  if (audio) form.append("audio", audio, "speech.wav");
  if (frame) form.append("image", frame, "frame.jpg");
  const t0 = performance.now();
  try {
    const res = await fetch("/api/turn", { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const data = await res.json();
    addMessage("visitor", data.transcript || text);
    addMessage("docent", data.reply);
    speak(data.reply);
    const total = Math.round(performance.now() - t0);
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

function captureFrame() {
  if (!video.videoWidth) return Promise.resolve(null);
  const scale = Math.min(1, 768 / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.75));
}

// 브라우저마다 녹음 형식(iOS: mp4/AAC, Chrome: webm/Opus)이 달라 16kHz 모노 WAV로 통일한다.
async function toWav16k(blob) {
  const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
  const rate = 16000;
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const writeStr = (o, s) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
  writeStr(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); writeStr(8, "WAVE");
  writeStr(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeStr(36, "data"); view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}
