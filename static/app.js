// AIVY mobile UI. UI integration by FE2; retain FE1's v0 session, camera, audio and /api/turn contract.
// IMPORTANT: region/age selection currently lives in this browser session only. BE1 must add a
// documented profile API before personalization can influence Gemini responses.
import { postTurn, startSession } from "./api.js";
import { initAudio, speak, stopSpeaking, toWav16k } from "./audio.js";
import { continueSavedVisit, createLiveConversation, createVisitStore, createWakeLock, FRAME_MAX_WIDTH } from "./live_conversation.js"; // FE1 Live 연결 (11/18)

const $ = (id) => document.getElementById(id);
const video = $("camera");
const talkBtn = $("talk");
const regionLanguages = {
  "north-america": "English",
  "europe": "English", // European region includes multiple languages; English is a provisional default.
  "china": "Chinese",
  "japan": "Japanese",
};
// 작품·비교 정보는 서버가 보내 준다(11/18, FE1). 전에는 이 파일에 손으로 베껴 뒀는데
// data/comparisons.csv가 20점으로 늘자 14개가 요약에서 사라지고 ID 하나는 죽었다.
let sessionId = null;
let stream = null;
let recorder = null;
let chunks = [];
let busy = false;
let lastReply = "";
let currentArtwork = "";
let currentComparison = "";
let returnScreen = "experience-screen";
const viewedArtworks = new Map(); // artwork_id => {title,artist,comparisons:Set}. Session memory only.
const MIN_WAV_BYTES = 8000;   // 사진 가로 크기는 live_conversation.js의 FRAME_MAX_WIDTH 하나를 쓴다

// ── FE1 Live 연결 (11/18) ─────────────────────────────────────────────────────────────
// 버튼 없는 대화(Live handsfree, static/live_conversation.js). START EXPLORING 뒤에 연다.
// Live가 열리면 마이크 버튼은 상태 표시·음소거 토글이 되고, 글 질문도 Live로 간다.
// 처음 연결에 실패하면 live=null로 두고 /api/turn 탭 녹음으로 전환한다. 도중 끊김·error는
// live_conversation.js가 END VISIT 전까지 스스로 다시 붙는다(버튼 방식으로 바꾸지 않는다. 글라스를 쓰면 누를 화면이 없다).
// 글라스를 쓰면 폰 화면이 꺼지므로 화면 꺼짐 막기(Wake Lock)를 시도하고, 숨김·다시 보임을 Live에 알린다.
// iOS는 오래 백그라운드에 있던 탭을 메모리 때문에 새로 불러올 수 있다(11/18 실기기 20초 잠금에서는 연결이 그대로 유지됐다). 대비해서 Live 관람의 식별자만 sessionStorage에 두고
// (대화·사진·음성은 저장하지 않는다), 새로 뜨면 "Tap to continue your visit"로 같은 관람을 잇는다.
let live = null;
const visitStore = createVisitStore();
let savedVisit = null; // 새로고침 뒤 이어 갈 관람. 버튼을 누르기 전까지만 있다.
let screenNote = false; // Wake Lock을 못 쓰면 "Keep the screen on" 안내를 한 번 보인다
const wakeLock = createWakeLock({ onUnsupported: () => { screenNote = true; } });
function showScreenNoteOnce() {
  if (screenNote !== true) return;
  screenNote = "shown";
  setStatus("Keep the screen on during your visit");
}
function setTalkLabel(label, hint) {
  talkBtn.querySelector(".talk-label").textContent = label;
  talkBtn.setAttribute("aria-label", label);
  document.querySelector(".talk-hint").textContent = hint;
}
function renderMicState(muted, hint) {
  talkBtn.classList.toggle("recording", !muted);
  talkBtn.classList.toggle("muted", muted);
  talkBtn.setAttribute("aria-pressed", String(muted));
  setTalkLabel(muted ? "Microphone off · tap to unmute" : "Microphone on · tap to mute", hint);
  talkBtn.setAttribute("aria-label", "Mute microphone");
}
function useTapToTalk() {
  live = null;
  stream?.getAudioTracks().forEach(track => { track.enabled = false; });
  renderMicState(true, "TAP TO UNMUTE · TAP AGAIN TO SEND");
}
function liveHandlers() {
  return {
    onStatus: ({ state, status, label }) => {
      setStatus(status);
      const active = state === "listening" || state === "speaking";
      talkBtn.disabled = !active && state !== "muted" && state !== "needs_tap";
      if (active || state === "muted") {
        renderMicState(!active, active ? "SPEAK FREELY · TAP TO MUTE" : "MICROPHONE MUTED · TAP TO UNMUTE");
      } else {
        talkBtn.classList.remove("recording", "muted");
        talkBtn.removeAttribute("aria-pressed");
        setTalkLabel(label, state === "needs_tap" ? "TAP TO RESUME AUDIO" : "PLEASE WAIT");
      }
    },
    onArtwork: (data) => {
      // Live는 함수를 부를 때마다 artwork를 보낸다. 같은 작품이면 칩·요약·지금 비교를 건드리지 않는다.
      if (data.artwork_id === currentArtwork && viewedArtworks.has(data.artwork_id)) return;
      recordArtwork(data); // {artwork_id, artwork_title}
    },
    onComparison: (data) => recordArtwork(data), // {artwork_id, comparison_id}: 요약·상세의 비교에 누적
    onMicStream: (fresh) => { // 마이크 트랙이 끝나 새로 얻었다. 기존 녹음 경로도 새 트랙을 쓰게 바꿔 끼운다.
      if (!stream) return;
      stream.getAudioTracks().forEach((t) => { stream.removeTrack(t); t.stop(); });
      fresh.getAudioTracks().forEach((t) => stream.addTrack(t));
    },
    onFallback: (reason) => {
      console.warn("Live stopped, falling back to /api/turn:", reason);
      useTapToTalk();
      talkBtn.disabled = !sessionId;
      setStatus("Live voice stopped. Tap to unmute; tap again to send your question.");
    },
  };
}
// 성공하면 true(인사는 Live가 말한다). 실패하면 false — 부른 쪽이 기존 인사·버튼 방식으로 계속한다.
async function startLive(conversation, session) {
  setStatus("Connecting to your guide…");
  // 값 이름 맞추기는 11/18 회의 의제. 지금은 화면 선택값을 그대로 보낸다.
  const profile = { country: $("region-select").value, age_group: $("age-select").value, language: "en" };
  try {
    await conversation.open({ sessionId: session.session_id, profile, stream });
    live = conversation;
    visitStore.save({ session_id: session.session_id, profile }); // 새로고침 뒤 잇기용 식별자만
    talkBtn.disabled = false;
    return true;
  } catch (error) {
    console.warn("Live unavailable, using /api/turn:", error.message);
    conversation.close();
    useTapToTalk();
    return false;
  }
}
// 카메라·마이크는 보안 컨텍스트에서만 열린다(https, 또는 http://localhost). 폰에서
// http://<노트북 IP>로 열면 navigator.mediaDevices 자체가 없어서 "reading 'getUserMedia'"만
// 보이고 원인을 알 수 없다. 그래서 (1) 첫 화면에서 미리 알리고 (2) 열 때 원인을 말한다.
// index.html은 고치지 않으려고 선택자로 안내 문구를 찾는다.
const MIC_BLOCKED = "this page is not on HTTPS, so the camera and microphone are blocked. "
  + "Open the https:// address, or http://localhost on this computer.";

function micAvailable() {
  return Boolean(globalThis.navigator?.mediaDevices?.getUserMedia);
}

function cameraAndMic(constraints) {
  if (!micAvailable()) throw new Error(MIC_BLOCKED);
  return navigator.mediaDevices.getUserMedia(constraints);
}

function warnIfMicBlocked() {
  if (micAvailable()) return;
  const note = document.querySelector(".prep-note");
  if (note) {
    const label = note.querySelector("strong");
    const text = note.querySelector("span");
    if (label) label.textContent = "THIS PAGE IS NOT ON HTTPS";
    if (text) text.textContent = "Camera and microphone are blocked. Open the https:// address, "
      + "or http://localhost on this computer.";
  }
  console.warn("mic blocked:", MIC_BLOCKED);
}

warnIfMicBlocked();

// 새로고침 뒤 "Tap to continue your visit"(사용자 동작 안). /api/session을 새로 만들지 않고 저장된 관람을 잇는다.
async function continueVisit() {
  const saved = savedVisit;
  savedVisit = null;
  talkBtn.disabled = true;
  const conversation = createLiveConversation({ log: $("log"), video, handlers: liveHandlers() });
  wakeLock.request();
  initAudio().catch(() => {}); // 브라우저 TTS·녹음 변환용 소리 장치도 사용자 동작 안에서 깨운다
  try {
    const { ready } = await continueSavedVisit({
      saved, conversation, store: visitStore,
      getMedia: async () => {
        stream = await cameraAndMic({
          video: { facingMode: "environment", width: { ideal: 1280 } },
          audio: { echoCancellation: true, noiseSuppression: true },
        });
        video.srcObject = stream;
        video.addEventListener("playing", () => { $("camera-empty").hidden = true; }, { once: true });
        return stream;
      },
    });
    sessionId = ready.session_id || saved.session_id;
    live = conversation;
    talkBtn.disabled = false;
  } catch (error) {
    // 기록은 continueSavedVisit이 지웠다. 첫 화면으로 돌아가 새 관람을 시작하게 한다.
    console.warn("Could not continue the visit:", error.message);
    stream = null;
    video.srcObject = null;
    useTapToTalk();
    talkBtn.disabled = true;
    $("start").disabled = false;
    setStatus("Ready to explore.");
    showScreen("welcome-screen");
  }
}
talkBtn.addEventListener("click", () => {
  if (savedVisit) { continueVisit(); return; }
  if (!live) { toggleRecording(); return; }
  if (live.needsTap) live.resumeAudio(); // "Tap to resume": 아이폰은 소리 장치를 깨우는 데 사용자 동작이 필요하다
  else live.toggleMuted();
});
document.addEventListener("visibilitychange", () => {
  const visible = document.visibilityState === "visible";
  if (visible && sessionId) wakeLock.request(); // 숨겨지면 브라우저가 자동으로 풀므로 다시 요청한다
  live?.setVisible(visible);
});
// 페이지가 뜰 때: 2시간 안의 Live 관람 기록이 있으면 첫 화면 대신 관람 화면과 이어 가기 버튼을 보인다.
// 대화 기록과 요약(viewedArtworks)은 브라우저 메모리라 새로고침 때 사라진다(서버 세션에는 남아 있다).
savedVisit = visitStore.load();
if (savedVisit) {
  showScreen("experience-screen");
  talkBtn.disabled = false;
  talkBtn.classList.remove("muted", "recording");
  talkBtn.removeAttribute("aria-pressed");
  setTalkLabel("Tap to continue your visit", "YOUR VISIT WAS PAUSED");
  setStatus("Your visit was paused. Tap the button below to continue.");
}
// ── FE1 Live 연결 끝 ──────────────────────────────────────────────────────────────────

function showScreen(id) {
  for (const name of ["welcome-screen", "experience-screen", "summary-screen"]) $(name).hidden = name !== id;
  $("page-tag").textContent = ({ "welcome-screen": "01 / 03", "experience-screen": "02 / 03", "summary-screen": "03 / 03" })[id];
  window.scrollTo({top:0,behavior:"instant"});
}
function setStatus(text) { $("status").textContent = text; }
function readReply(text) {
  $("audio-status").textContent = "Preparing voice…";
  speak(text, {
    onStart: () => { $("audio-status").textContent = "Speaking…"; },
    onEnd: () => { $("audio-status").textContent = "Voice finished."; },
    onError: (code) => { $("audio-status").textContent = "Audio error: " + code + ". Try Replay response."; },
  });
}
function rememberReply(text) {
  lastReply = text || "";
  $("replay").disabled = !lastReply;
  if (lastReply) readReply(lastReply);
}
function addMessage(who,text) {
  if (!text) return;
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}
function getSelectedRegion() {
  return $("region-select").options[$("region-select").selectedIndex]?.text || "North America";
}
function updateLanguageLabel() { $("language-value").textContent = regionLanguages[$("region-select").value] || "English"; }
$("region-select").addEventListener("change", updateLanguageLabel);
updateLanguageLabel();

function recordArtwork(data) {
  const id = data.artwork_id;
  if (!id || id === "unknown") return;
  if (!viewedArtworks.has(id)) viewedArtworks.set(id, {
    title: data.artwork_title || id, artist: data.artist || "Joseon artwork", comparisons: new Map(),
  });
  const entry = viewedArtworks.get(id);
  if (data.artwork_title) entry.title = data.artwork_title;
  if (data.artist) entry.artist = data.artist;
  // 비교는 서버가 보내 준 제목·작가·소장처를 그대로 쌓는다. 제목이 없으면 그릴 것이 없으니 세지 않는다.
  if (data.comparison_id && data.foreign_title)
    entry.comparisons.set(data.comparison_id, {
      title: data.foreign_title, artist: data.foreign_artist || "",
      collection: data.foreign_collection || "", url: data.foreign_url || "",
    });
  currentArtwork = id;
  currentComparison = data.comparison_id && entry.comparisons.has(data.comparison_id) ? data.comparison_id : "";
  $("recognized-title").textContent = entry.title;
  $("artwork-shortcut").hidden = false;
}
function renderSummary() {
  $("count-artworks").textContent = String(viewedArtworks.size).padStart(2,"0");
  const count = Array.from(viewedArtworks.values()).reduce((s,item)=>s+item.comparisons.size,0);
  $("count-comparisons").textContent = String(count).padStart(2,"0");
  const root = $("summary-list");
  root.replaceChildren();
  if (!viewedArtworks.size) {
    const empty = document.createElement("div");
    empty.className = "summary-empty";
    empty.textContent = "No artworks recognized yet. Explore a painting to begin your art journey.";
    root.appendChild(empty);
    return;
  }
  let i=0;
  for (const [id,item] of viewedArtworks) {
    const card=document.createElement("article");card.className="summary-card";
    const tag=document.createElement("div");tag.className="summary-label";tag.textContent=String(++i).padStart(2,"0")+"  KOREAN ARTWORK";
    const title=document.createElement("h3");title.textContent=item.title;
    const artist=document.createElement("p");artist.textContent=item.artist;
    card.append(tag,title,artist);
    if (!item.comparisons.size) {
      const line=document.createElement("div");line.className="pair-divider";
      const label=document.createElement("div");label.className="summary-label";label.textContent="NO COMPARISON USED";
      card.append(line,label);
    } else {
      for (const match of item.comparisons.values()) {
        const line=document.createElement("div");line.className="pair-divider";
        const label=document.createElement("div");label.className="summary-label";label.textContent="↳  PAIRED WITH";
        const foreign=document.createElement("h3");foreign.textContent=match.title;
        const meta=document.createElement("p");meta.textContent=[match.artist,match.collection].filter(Boolean).join(" · ");
        card.append(line,label,foreign,meta);
      }
    }
    root.appendChild(card);
  }
}
function showSummary() { renderSummary(); showScreen("summary-screen"); }
function showDetails() {
  if (!currentArtwork || !viewedArtworks.has(currentArtwork)) return;
  const art=viewedArtworks.get(currentArtwork);
  $("details-title").textContent=art.title;
  $("details-subtitle").textContent=art.artist;
  const c=art.comparisons.get(currentComparison);
  $("details-comparison").hidden=!c;
  if(c) {
    $("comparison-title").textContent=c.title;
    $("comparison-subtitle").textContent=[c.artist,c.collection].filter(Boolean).join(" · ");
    $("comparison-link").href=c.url;
    $("comparison-link").hidden=!c.url;
  }
  $("details-overlay").hidden=false;
  $("close-details").focus();
}
function closeDetails() { $("details-overlay").hidden=true; $("artwork-shortcut").focus(); }
$("artwork-shortcut").addEventListener("click",showDetails);
$("close-details").addEventListener("click",closeDetails);
$("details-done").addEventListener("click",closeDetails);
document.querySelector("[data-close-details]").addEventListener("click",closeDetails);
document.addEventListener("keydown",event=>{ if(event.key==="Escape"&&!$("details-overlay").hidden)closeDetails(); });
$("view-summary").addEventListener("click",showSummary);
$("finish").addEventListener("click",showSummary);
$("back-to-guide").addEventListener("click",()=>showScreen("experience-screen"));
$("test-voice").addEventListener("click",()=>readReply("Hello. Welcome to your AIVY museum guide."));
$("replay").addEventListener("click",()=>{ if(!busy&&lastReply)readReply(lastReply); });

$("onboarding-form").addEventListener("submit",async event=>{
  event.preventDefault();
  if(sessionId)return;
  $("start").disabled=true;
  // FE1 Live 연결 (11/18): 아이폰은 사용자 동작 안, 첫 await 전에 소리를 깨워야 한다.
  const pendingLive=createLiveConversation({log:$("log"),video,handlers:liveHandlers()});
  pendingLive.prime();
  wakeLock.request(); // 사용자 동작 안에서 화면 꺼짐 막기를 요청한다. 못 쓰면 조용히 넘어간다.
  // Local UI selection does not yet go to Gemini. Do not pretend profile sync succeeded.
  try{
    await initAudio();
    stream=await cameraAndMic({
      video:{facingMode:"environment",width:{ideal:1280}},
      audio:{echoCancellation:true,noiseSuppression:true},
    });
    video.srcObject=stream;
    video.addEventListener("playing",()=>{$("camera-empty").hidden=true;},{once:true});
    const data=await startSession();
    sessionId=data.session_id;
    showScreen("experience-screen");
    // FE1 Live 연결 (11/18): Live가 열리면 첫 인사도 Live가 말한다(speechSynthesis로 읽지 않는다).
    if(await startLive(pendingLive,data)){showScreenNoteOnce();return;}
    // Live를 못 열면 탭 녹음 방식으로 질문을 보낸다.
    addMessage("docent",data.reply);
    rememberReply(data.reply);
    talkBtn.disabled=false;
    setStatus("Point the camera at an artwork. Tap to unmute; tap again to send.");
    showScreenNoteOnce(); // FE1 Live 연결 (11/18)
  }catch(error){
    pendingLive.close(); // FE1 Live 연결 (11/18)
    if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
    $("start").disabled=false;
    alert("Could not start visit: "+error.message);
  }
});

function toggleRecording() {
  if(busy||!stream||!sessionId||talkBtn.disabled)return;
  if(recorder?.state === "recording") {
    // Lock immediately: MediaRecorder.onstop and WAV decoding are asynchronous.
    talkBtn.disabled = true;
    recorder.stop();
    stream.getAudioTracks().forEach(track => { track.enabled = false; });
    renderMicState(true, "PREPARING YOUR QUESTION…");
    return;
  }
  if(!window.MediaRecorder){setStatus("Audio recording is unsupported in this browser. Use the text field.");return;}
  stopSpeaking();
  $("replay").disabled=true;$("test-voice").disabled=true;
  chunks=[];
  try {
    stream.getAudioTracks().forEach(track => { track.enabled = true; });
    recorder=new MediaRecorder(new MediaStream(stream.getAudioTracks()));
    recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    recorder.onstop=onRecordingStop;
    recorder.start();
    renderMicState(false, "SPEAK YOUR QUESTION · TAP TO MUTE & SEND");
    setStatus("Listening… tap to mute and send your question.");
  } catch(error) {
    useTapToTalk();
    setStatus("Recording unavailable: "+error.message);
    $("replay").disabled=!lastReply;$("test-voice").disabled=false;
  }
}
async function onRecordingStop(){
  const recordingSession = sessionId;
  const blob=new Blob(chunks,{type:recorder.mimeType});
  busy=true;
  try {
    const wav=await toWav16k(blob);
    if(sessionId !== recordingSession)return;
    if(wav.size<MIN_WAV_BYTES){setStatus("Too short. Tap to unmute and speak before tapping again.");return;}
    const frame=await captureFrame();
    busy=false;
    await sendTurn({audio:wav,frame});
  } catch(error) {
    setStatus("Could not prepare recording: "+error.message);
  } finally {
    busy=false;
    talkBtn.disabled=!sessionId;
    $("replay").disabled=!lastReply;$("test-voice").disabled=false;
    renderMicState(true, "TAP TO UNMUTE · TAP AGAIN TO SEND");
  }
}
$("text-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const text=$("text-input").value.trim();
  if(!text||!sessionId||busy)return;
  if(recorder?.state === "recording"){setStatus("Tap to mute and send your voice question first.");return;}
  $("text-input").value="";
  if(live&&live.sendText(text))return; // FE1 Live 연결 (11/18): 글 질문도 Live로. 못 보내면 기존 방식
  await sendTurn({text,frame:await captureFrame()});
});
async function sendTurn({audio,text,frame}){
  if(!sessionId||busy)return;
  busy=true;stopSpeaking();
  $("replay").disabled=true;$("test-voice").disabled=true;talkBtn.disabled=true;
  setStatus("Thinking…");
  const started=performance.now();
  try{
    const data=await postTurn({sessionId,audio,text,frame});
    addMessage("visitor",data.transcript||text||"Voice question");
    addMessage("docent",data.reply);
    recordArtwork(data);
    rememberReply(data.reply);
    const total=Math.round(performance.now()-started);
    const profile=data.profile||{};
    $("meta").textContent="artwork: "+(data.artwork_title||data.artwork_id||"-")+
      " · comparison: "+(data.comparison_id||"-")+
      " · server profile: "+(profile.country||"unset")+" · total "+total+" ms";
    setStatus("Ask another question or review your artwork.");
  }catch(error){
    setStatus("Request failed: "+error.message);
  }finally{
    busy=false;$("replay").disabled=!lastReply;$("test-voice").disabled=false;
    talkBtn.disabled=false;
  }
}
function captureFrame(){
  if(!video.videoWidth)return Promise.resolve(null);
  const scale=Math.min(1,FRAME_MAX_WIDTH/video.videoWidth);
  const canvas=document.createElement("canvas");
  canvas.width=Math.round(video.videoWidth*scale);
  canvas.height=Math.round(video.videoHeight*scale);
  canvas.getContext("2d").drawImage(video,0,0,canvas.width,canvas.height);
  return new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.75)); 
}
$("end-visit").addEventListener("click",async()=>{
  if(busy)return;
  $("end-visit").disabled=true;
  stopSpeaking();
  if(live){live.close();useTapToTalk();} // FE1 Live 연결 (11/18): 마이크·사진 전송을 멈추고 WS를 닫는다
  wakeLock.release();visitStore.clear();savedVisit=null; // FE1 Live 연결 (11/18): 관람 기록도 지운다
  if(recorder?.state==="recording"){recorder.onstop=null;recorder.stop();}
  if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
  video.srcObject=null;
  try{
    if(sessionId) {
      const r=await fetch("/api/session/"+encodeURIComponent(sessionId)+"/end",{method:"POST"});
      if(!r.ok)throw new Error("Server returned "+r.status);
    }
    sessionId=null;recorder=null;chunks=[];lastReply="";currentArtwork="";currentComparison="";
    viewedArtworks.clear();$("log").replaceChildren();$("recognized-title").textContent="";
    $("artwork-shortcut").hidden=true;$("camera-empty").hidden=false;
    $("replay").disabled=true;talkBtn.disabled=true;$("start").disabled=false;
    $("audio-status").textContent="";$("meta").textContent="";
    $("details-overlay").hidden=true;showScreen("welcome-screen");
  }catch(error){
    $("end-visit").disabled=false;
    alert("Could not end the server session: "+error.message+". Please retry.");
    return;
  }
  $("end-visit").disabled=false;
});
