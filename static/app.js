// AIVY mobile UI. UI integration by FE2; retain FE1's v0 session, camera, audio and /api/turn contract.
// IMPORTANT: region/age selection currently lives in this browser session only. BE1 must add a
// documented profile API before personalization can influence Gemini responses.
import { postTurn, startSession } from "./api.js";
import { initAudio, speak, stopSpeaking, toWav16k } from "./audio.js";

const $ = (id) => document.getElementById(id);
const video = $("camera");
const talkBtn = $("talk");
const regionLanguages = {
  "north-america": "English",
  "europe": "English", // European region includes multiple languages; English is a provisional default.
  "china": "Chinese",
  "japan": "Japanese",
};
const artworkCatalog = {
  JS_INWANG: { title: "Inwang jesaekdo (Scene of Inwangsan Mountain After Rain)", artist: "Jeong Seon · 1751" },
  KHD_SSIREUM: { title: "Korean Traditional Wrestling", artist: "Kim Hong-do · Late 18th century" },
  KHD_SEODANG: { title: "A Village School", artist: "Kim Hong-do · Late 18th century" },
  KSH_SELF: { title: "Portrait of Kang Se-hwang", artist: "Kang Se-hwang · 1782" },
  KJH_SEHAN: { title: "Sehando (Winter Scene)", artist: "Kim Jeong-hui · 1844" },
  LIM_GANGSAN: { title: "Rivers and Mountains without End", artist: "Yi In-mun · Early 19th century" },
  KHD_CHUSEONG: { title: "Chuseongbudo (Sounds of Autumn)", artist: "Kim Hong-do · 1805" },
  SYB_BABY: { title: "Woman Carrying a Baby on Her Back", artist: "Shin Yun-bok · Late Joseon" },
  CHAEKGADO_6: { title: "Chaekgado (Bookshelf Painting)", artist: "Unknown · Late 18th century" },
  LA_DOGS: { title: "Painting of a Dog and Puppies", artist: "Yi Am · 16th century" },
  SSD_CHOCHUNG: { title: "Plants and Insects", artist: "Attributed to Shin Saimdang · Joseon" },
};
// Verified comparison records from data/comparisons.csv; do not claim a comparison unless the API returns its id.
const comparisonCatalog = {
  C_INWANG_CEZANNE: { artwork: "JS_INWANG", title: "Mont Sainte-Victoire", artist: "Paul Cézanne", collection: "The Metropolitan Museum of Art", url: "https://www.metmuseum.org/art/collection/search/435878" },
  C_INWANG_HOKUSAI: { artwork: "JS_INWANG", title: "South Wind, Clear Sky (Red Fuji)", artist: "Katsushika Hokusai", collection: "The Metropolitan Museum of Art", url: "https://www.metmuseum.org/art/collection/search/36490" },
  C_KHD_BRUEGEL: { artwork: "KHD_SSIREUM", title: "Peasant Wedding", artist: "Pieter Bruegel the Elder", collection: "Kunsthistorisches Museum Vienna", url: "https://www.khm.at/en/objectdb/detail/330/" },
  C_SEODANG_BRUEGEL: { artwork: "KHD_SEODANG", title: "Children's Games", artist: "Pieter Bruegel the Elder", collection: "Kunsthistorisches Museum Vienna", url: "https://www.khm.at/en/objectdb/detail/321/" },
};
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
const MIN_WAV_BYTES = 8000, FRAME_MAX_WIDTH = 768;

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
  const known = artworkCatalog[id] || {};
  if (!viewedArtworks.has(id)) viewedArtworks.set(id, {
    title: data.artwork_title || known.title || id, artist: known.artist || "Joseon artwork", comparisons: new Set(),
  });
  const entry = viewedArtworks.get(id);
  if (data.artwork_title) entry.title = data.artwork_title;
  if (data.comparison_id && comparisonCatalog[data.comparison_id]?.artwork === id)
    entry.comparisons.add(data.comparison_id);
  currentArtwork = id;
  currentComparison = data.comparison_id && comparisonCatalog[data.comparison_id]?.artwork === id ? data.comparison_id : "";
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
      for (const id of item.comparisons) {
        const match=comparisonCatalog[id];if(!match)continue;
        const line=document.createElement("div");line.className="pair-divider";
        const label=document.createElement("div");label.className="summary-label";label.textContent="↳  PAIRED WITH";
        const foreign=document.createElement("h3");foreign.textContent=match.title;
        const meta=document.createElement("p");meta.textContent=match.artist+" · "+match.collection;
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
  const c=comparisonCatalog[currentComparison];
  $("details-comparison").hidden=!c;
  if(c) {
    $("comparison-title").textContent=c.title;
    $("comparison-subtitle").textContent=c.artist+" · "+c.collection;
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
  // Local UI selection does not yet go to Gemini. Do not pretend profile sync succeeded.
  try{
    await initAudio();
    stream=await navigator.mediaDevices.getUserMedia({
      video:{facingMode:"environment",width:{ideal:1280}},
      audio:{echoCancellation:true,noiseSuppression:true},
    });
    video.srcObject=stream;
    video.addEventListener("playing",()=>{$("camera-empty").hidden=true;},{once:true});
    const data=await startSession();
    sessionId=data.session_id;
    showScreen("experience-screen");
    addMessage("docent",data.reply);
    rememberReply(data.reply);
    talkBtn.disabled=false;
    setStatus("Point the camera at an artwork and hold the talk button.");
  }catch(error){
    if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
    $("start").disabled=false;
    alert("Could not start visit: "+error.message);
  }
});

talkBtn.addEventListener("pointerdown",event=>{
  event.preventDefault();
  if(busy||!stream||!sessionId)return;
  if(!window.MediaRecorder){setStatus("Audio recording is unsupported in this browser. Use the text field.");return;}
  stopSpeaking();
  $("replay").disabled=true;$("test-voice").disabled=true;
  chunks=[];
  try{
    recorder=new MediaRecorder(new MediaStream(stream.getAudioTracks()));
    recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    recorder.onstop=onRecordingStop;
    recorder.start();
    talkBtn.setPointerCapture?.(event.pointerId);
    talkBtn.classList.add("recording");
    talkBtn.querySelector(".talk-label").textContent="Listening… release to send";
    setStatus("Listening…");
  }catch(error){setStatus("Recording unavailable: "+error.message);$("test-voice").disabled=false;}
});
for(const type of ["pointerup","pointercancel","lostpointercapture"]){
  talkBtn.addEventListener(type,()=>{
    if(recorder?.state==="recording")recorder.stop();
    talkBtn.classList.remove("recording");
    talkBtn.querySelector(".talk-label").textContent="Hold to talk";
  });
}
async function onRecordingStop(){
  $("replay").disabled=!lastReply;$("test-voice").disabled=false;
  const blob=new Blob(chunks,{type:recorder.mimeType});
  let wav;
  try{wav=await toWav16k(blob);}
  catch(error){setStatus("Could not decode recording: "+error.message);return;}
  if(wav.size<MIN_WAV_BYTES){setStatus("Too short. Hold the button while speaking.");return;}
  await sendTurn({audio:wav,frame:await captureFrame()});
}
$("text-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const text=$("text-input").value.trim();
  if(!text||!sessionId||busy)return;
  $("text-input").value="";
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
  if(recorder?.state==="recording")recorder.stop();
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
