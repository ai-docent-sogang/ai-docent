// AIVY 화면에서 버튼 없이 Live로 대화하는 부분("handsfree" 모드).
//
// 담당: FE1
// 같이 보는 파일: app.js (FE2 화면. 이 파일을 열고 닫고, 처음 연결에 실패하면 기존 /api/turn 방식으로 되돌아감),
//               live_mic_worklet.js (마이크 16kHz PCM), live_player.js (답변 24kHz PCM 재생),
//               live_test.js (같은 서버와 push 모드로 대화하는 시험 페이지. 아이폰 제약의 근거),
//               server/live.py (WS /ws/live, T1), 메시지 형식은 '버튼 없는 대화 계약'(2026-11-18)
//
// 하는 일:
//   - WS /ws/live를 열고 첫 메시지로 {mode:"handsfree", session_id, profile}을 보낸다.
//   - 마이크를 말이 없을 때도 계속 16kHz PCM16으로 보낸다. 말의 시작·끝은 서버·Gemini의 자동 음성
//     감지가 판단한다. 음소거하면 무음 600ms를 보낸 뒤 멈춘다(감지가 말의 끝을 보게).
//   - 답변 음성(24kHz PCM)을 이어 재생하고, interrupted가 오면 즉시 멈춘다(관람객이 말을 끊음).
//   - 3초마다 카메라 사진(JPEG, 가로 최대 768px, 화질 0.7)을 base64로 보낸다.
//   - heard/said 조각을 말풍선에 이어 붙이고 turn_complete에서 끝낸다.
//   - artwork/comparison은 handlers로 넘긴다(app.js가 요약·상세에 기록).
//
// 실패와 끊김을 나눈다(2026-11-18 수정. 글라스를 쓰면 폰 화면이 꺼져 연결이 자주 끊긴다):
//   - 처음 open()이 ready까지 가지 못하면 open()이 거절된다 → app.js가 기존 버튼 방식으로 대체.
//   - ready 뒤의 끊김·error는 대체하지 않고 자동 재연결한다. 1s, 2s, 4s, 8s, 15s, 이후 15s 간격으로 close()
//     (END VISIT) 전까지 계속. 글라스를 쓰면 폰 화면이 오래 꺼져 있는 게 정상이고, 그때 버튼 방식으로 바뀌어도
//     누를 화면이 없다(11/18 결정). 다시 붙을 때 첫 메시지에 "resume": true를 더한다(같은 session_id·profile).
//     그 사이 마이크·사진은 보내지 않는다.
//   - 페이지가 숨겨지면(setVisible(false)) 마이크·사진 전송만 멈추고 소켓은 그대로 둔다. 다시 보이면 재개하고,
//     소켓이 죽었으면 기다리던 간격을 버리고 바로 재연결한다(간격도 1초부터 다시). 소리 장치가 멈춰 있으면 resume하고, 안 되면 onNeedsTap(한 번 누르면 resumeAudio()).
//
// 살아 있음 알림: ready 뒤 5초마다 {"type":"ping"}을 보낸다(숨김 중에도 소켓이 열려 있으면). 서버는 30초 동안
// 폰에서 아무것도 못 받으면 연결을 닫는다(T1). 닫히면 위의 재연결이 잇는다.
//
// 새로고침 뒤 관람 잇기(11/18, iOS가 오래 숨겨진 탭을 새로 불러올 때를 대비. 20초 잠금에서는 새로고침 없이 연결이 유지됐다): createVisitStore()가 sessionStorage에
// {session_id, profile, started_at}만 저장한다(대화·사진·음성은 저장하지 않는다 — AGENTS.md). 페이지가 다시 뜨면
// continueSavedVisit()이 같은 session_id로 resume:true 연결을 연다(/api/session을 새로 만들지 않는다).
//
// 아이폰 Safari 주의: AudioContext는 사용자가 누른 흐름 안에서, 첫 await 전에 만들어야 한다.
// 그래서 prime()을 따로 두었다. START EXPLORING 처리의 맨 앞에서 부른다(live_test.js와 같은 이유).
// 카메라 사진과 음성은 보내기만 하고 저장하지 않는다(AGENTS.md).

import { createPlayer } from "./live_player.js";

export const FRAME_INTERVAL_MS = 3000;
// 사진 가로 최대 크기. **두 경로가 함께 쓰는 단일 출처다** — app.js가 이것을 가져다 쓴다.
// 11/18에 BE2 요청으로 768 → 1100으로 올렸다(인식 정확도). 두 곳에 따로 적어 두었더니
// app.js만 1100이 되고 Live(주 경로)는 768에 머물러 요청이 반영되지 않았다.
// 올리면 들어가는 사진 토큰도 늘어난다(실측에서 사진은 관람 토큰의 5%였다).
export const FRAME_MAX_WIDTH = 1100;
export const FRAME_QUALITY = 0.7;
// ready가 이 시간 안에 오지 않으면 그 연결 시도는 실패로 본다.
export const OPEN_TIMEOUT_MS = 12000;
// ready 뒤 끊겼을 때 다시 붙는 간격. 기한 없이 END VISIT 전까지 시도한다.
export const RECONNECT_FIRST_MS = 1000;
export const RECONNECT_MAX_GAP_MS = 15000;
// 음소거할 때 보내는 무음 길이. 마이크 조각이 100ms(1600샘플)이므로 6조각.
export const MUTE_SILENCE_MS = 600;
export const PING_INTERVAL_MS = 5000;
// 새로고침 뒤 이어 갈 수 있는 관람 기록의 최대 나이.
export const VISIT_MAX_AGE_MS = 2 * 60 * 60 * 1000;
const VISIT_KEY = "aivy.liveVisit";
const CHUNK_SAMPLES = 1600;
const CHUNK_MS = 100;

function defaultUrl() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/live`;
}

// #camera 영상에서 JPEG을 뽑아 base64 글자로 돌려준다. 영상이 아직 없으면 null.
function captureJpegBase64(video) {
  if (!video || !video.videoWidth) return null;
  const scale = Math.min(1, FRAME_MAX_WIDTH / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", FRAME_QUALITY);
  const comma = dataUrl.indexOf(",");
  return comma < 0 ? null : dataUrl.slice(comma + 1);
}

// 마이크 준비. prime()은 사용자 동작 안에서(동기로) AudioContext를 만들고,
// start()는 그 뒤에 worklet을 붙여 100ms(1600샘플)마다 onChunk(Int16Array)를 부른다.
function createWorkletMic() {
  let ctx = null;
  let node = null;
  let source = null;
  let track = null;
  function connectTrack(stream) {
    track = stream?.getAudioTracks?.()[0];
    if (!track) throw new Error("no microphone track");
    try { source?.disconnect(); } catch { /* 이미 끊김 */ }
    // 관람 시작 때 연 마이크를 그대로 쓴다(아이폰에서 마이크를 두 번 열면 앞의 것이 멈출 수 있다).
    source = ctx.createMediaStreamSource(new MediaStream([track]));
    source.connect(node);
  }
  return {
    prime() {
      if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume(); // await하지 않는다. 사용자 동작 안에서 부르는 것이 중요하다.
    },
    async start(stream, onChunk) {
      if (!window.AudioWorklet || !ctx) throw new Error("AudioWorklet unavailable");
      if (!stream?.getAudioTracks?.()[0]) throw new Error("no microphone track");
      if (ctx.state === "suspended") await ctx.resume();
      await ctx.audioWorklet.addModule("/static/live_mic_worklet.js");
      node = new AudioWorkletNode(ctx, "mic-downsampler");
      node.port.onmessage = (event) => onChunk(event.data);
      connectTrack(stream);
      // 아이폰에서 AudioWorklet이 멈추지 않도록 destination에 붙인다. 소리는 내보내지 않는다.
      const silent = ctx.createGain();
      silent.gain.value = 0;
      node.connect(silent).connect(ctx.destination);
    },
    /** 새로 얻은 마이크 스트림으로 바꿔 끼운다(트랙이 ended가 된 뒤). */
    restart(stream) { if (ctx && node) connectTrack(stream); },
    trackEnded() { return Boolean(track && track.readyState === "ended"); },
    /** 멈춘 AudioContext를 깨운다. 사용자 동작 안에서 부르면 아이폰에서도 된다. 돌아가면 true. */
    async resume() {
      if (!ctx) return true;
      if (ctx.state !== "running") await ctx.resume();
      return ctx.state === "running";
    },
    stop() {
      try { source?.disconnect(); node?.disconnect(); } catch { /* 이미 끊김 */ }
      if (node) node.port.onmessage = null;
      node = source = track = null;
      if (ctx && ctx.state !== "closed") ctx.close().catch(() => {});
      ctx = null;
    },
  };
}

/**
 * 화면 꺼짐 막기(Screen Wake Lock). request()는 START 처리(사용자 동작) 안에서 한 번, 그 뒤 페이지가
 * 다시 보일 때마다 부른다(숨겨지면 브라우저가 자동으로 푼다). 지원하지 않거나 거절되면 조용히 false를
 * 돌려주고 onUnsupported를 한 번만 부른다. iOS Safari는 18.4부터 지원(caniuse, 16.4~18.3 부분 지원).
 */
export function createWakeLock({ nav = globalThis.navigator, onUnsupported } = {}) {
  let sentinel = null;
  let warned = false;
  const warn = () => { if (!warned) { warned = true; onUnsupported?.(); } };
  return {
    async request() {
      if (!nav?.wakeLock?.request) { warn(); return false; }
      try {
        sentinel = await nav.wakeLock.request("screen");
        sentinel?.addEventListener?.("release", () => { sentinel = null; });
        return true;
      } catch {
        warn();
        return false;
      }
    },
    async release() {
      const s = sentinel;
      sentinel = null;
      try { await s?.release?.(); } catch { /* 이미 풀림 */ }
    },
    get active() { return Boolean(sentinel); },
  };
}

/**
 * 관람 식별자 기록(sessionStorage). 식별자만 저장한다: {session_id, profile, started_at}.
 * load()는 VISIT_MAX_AGE_MS(2시간) 안의 기록만 돌려주고, 오래됐거나 깨진 기록은 지운다.
 * 저장소를 못 쓰면(사생활 보호 모드 등) 조용히 아무것도 하지 않는다.
 */
export function createVisitStore({ storage, now = () => Date.now(), maxAgeMs = VISIT_MAX_AGE_MS } = {}) {
  const store = () => {
    try { return storage || globalThis.sessionStorage || null; } catch { return null; }
  };
  const clear = () => { try { store()?.removeItem(VISIT_KEY); } catch { /* 저장소 없음 */ } };
  return {
    save({ session_id, profile }) {
      if (!session_id) return;
      try {
        store()?.setItem(VISIT_KEY, JSON.stringify({ session_id, profile: profile || {}, started_at: now() }));
      } catch { /* 저장소 없음 */ }
    },
    load() {
      let rec = null;
      try { rec = JSON.parse(store()?.getItem(VISIT_KEY) || "null"); } catch { rec = null; }
      const age = rec ? now() - rec.started_at : NaN;
      if (!rec || typeof rec.session_id !== "string" || !rec.session_id || !(age >= 0 && age <= maxAgeMs)) {
        clear();
        return null;
      }
      return { session_id: rec.session_id, profile: rec.profile || {}, started_at: rec.started_at };
    },
    clear,
  };
}

/**
 * 새로고침 뒤 "Tap to continue your visit"를 눌렀을 때(사용자 동작 안에서) 부른다.
 * 카메라·마이크를 다시 얻고, 저장된 session_id로 resume:true 연결을 연다. /api/session은 부르지 않는다.
 * 성공하면 {stream, ready}. 실패하면 기록을 지우고 얻은 장치를 멈춘 뒤 거절한다(부른 쪽이 첫 화면으로).
 */
export async function continueSavedVisit({ saved, conversation, store, getMedia }) {
  conversation.prime(); // 첫 await 전에(아이폰 Safari)
  let stream = null;
  try {
    stream = await getMedia();
    const ready = await conversation.open({
      sessionId: saved.session_id, profile: saved.profile, stream, resume: true,
    });
    return { stream, ready };
  } catch (err) {
    conversation.close();
    stream?.getTracks?.().forEach((t) => t.stop());
    store?.clear();
    throw err;
  }
}

// 말풍선 이어 붙이기. 같은 턴의 조각은 같은 말풍선에 붙이고, 턴이 끝나면 다음 조각은 새 말풍선으로.
export function createTranscript(log, doc = globalThis.document) {
  let visitor = null;
  let docent = null;
  function bubble(who) {
    const div = doc.createElement("div");
    div.className = "msg " + who;
    div.textContent = "";
    log.appendChild(div);
    return div;
  }
  function scroll() { log.scrollTop = log.scrollHeight; }
  return {
    heard(text) {
      if (!text) return;
      if (!visitor) visitor = bubble("visitor");
      visitor.textContent += text;
      scroll();
    },
    said(text) {
      if (!text) return;
      if (!docent) docent = bubble("docent");
      docent.textContent += text;
      scroll();
    },
    /** 글로 물은 질문. 받아쓰기가 오지 않으므로 화면이 직접 말풍선을 만든다. */
    typed(text) {
      visitor = null;
      docent = null;
      bubble("visitor").textContent = text;
      scroll();
    },
    end() { visitor = null; docent = null; },
  };
}

const STATUS = {
  connecting: { status: "Connecting to your guide…", label: "Connecting…" },
  listening: { status: "I'm listening. Just talk — point the camera at a painting.", label: "Listening · tap to mute" },
  speaking: { status: "AIVY is speaking… you can interrupt anytime.", label: "Listening · tap to mute" },
  muted: { status: "Microphone muted. Tap the button to talk again.", label: "Muted · tap to unmute" },
  reconnecting: { status: "Reconnecting…", label: "Reconnecting…" },
  paused: { status: "Paused while the screen is off.", label: "Paused" },
  needs_tap: { status: "Sound is paused. Tap the button once to resume.", label: "Tap to resume" },
};

/**
 * handsfree 대화 하나. 부르는 순서: prime()(사용자 동작 안, 첫 await 전) → await open(...) →
 * sendText()/setMuted()/setVisible() → close().
 *
 * handlers: onStatus({state,status,label}), onReady(data), onReconnected(data), onArtwork(data),
 *           onComparison(data), onTurnComplete(), onFallback(reason), onNeedsTap(), onMicStream(stream)
 *           (onFallback은 지금 부르지 않는다. 대체는 처음 open() 거절뿐이다. 앞으로를 위해 자리만 둔다.)
 *           — 모두 없어도 된다.
 * deps(시험용): WebSocketImpl, player, mic, captureFrame, timers, getUserMedia, url,
 *               frameIntervalMs, openTimeoutMs, doc
 */
export function createLiveConversation({ handlers = {}, log, video, ...deps } = {}) {
  const WS = deps.WebSocketImpl || globalThis.WebSocket;
  const player = deps.player || createPlayer();
  const mic = deps.mic || createWorkletMic();
  const captureFrame = deps.captureFrame || (() => captureJpegBase64(video));
  const timers = deps.timers || globalThis;
  const getUserMedia = deps.getUserMedia ||
    ((c) => globalThis.navigator.mediaDevices.getUserMedia(c));
  const frameIntervalMs = deps.frameIntervalMs ?? FRAME_INTERVAL_MS;
  const openTimeoutMs = deps.openTimeoutMs ?? OPEN_TIMEOUT_MS;
  const transcript = log ? createTranscript(log, deps.doc) : null;

  let socket = null;
  let hello = null; // 첫 메시지 {mode, session_id, profile}. 재연결 때 resume:true를 더해 다시 보낸다.
  let ready = false; // 지금 소켓이 ready 상태인가
  let closed = false; // close() 또는 대체로 끝났는가
  let muted = false;
  let silenceLeft = 0; // 음소거 뒤 무음으로 바꿔 보낼 조각 수
  let hidden = false;
  let needsTap = false;
  let serverReconnecting = false; // 서버가 Gemini 세션을 다시 맺는 중(서버의 reconnecting 메시지)
  let linkDown = false; // 폰↔서버 소켓이 끊겨 우리가 다시 붙는 중
  let attempt = 0;
  let retryTimer = null;
  let attemptInFlight = false;
  let frameTimer = null;
  let pingTimer = null;
  let everReady = false; // 이 대화에서 ready를 한 번이라도 받았는가(onReady/onReconnected 구분)
  let state = "connecting";
  const stats = { audioChunksSent: 0, silenceChunksSent: 0, framesSent: 0, reconnectAttempts: 0 };

  function emit(next) {
    state = next;
    handlers.onStatus?.({ state: next, ...STATUS[next] });
  }
  const idleState = () => (needsTap ? "needs_tap" : hidden ? "paused" : muted ? "muted" : "listening");
  const isOpen = () => socket && socket.readyState === 1; // WebSocket.OPEN
  // 마이크·사진을 보내도 되는가
  const canSend = () => ready && !closed && !linkDown && !hidden && isOpen();

  function sendJson(obj) {
    if (!isOpen()) return false;
    socket.send(JSON.stringify(obj));
    return true;
  }

  function onMicChunk(pcm) {
    if (!canSend()) return;
    if (muted) {
      if (silenceLeft <= 0) return;
      silenceLeft -= 1;
      socket.send(new Int16Array(pcm.length || CHUNK_SAMPLES).buffer); // 무음
      stats.silenceChunksSent += 1;
      return;
    }
    socket.send(pcm.buffer);
    stats.audioChunksSent += 1;
  }

  function sendFrame() {
    if (!canSend()) return;
    const jpeg = captureFrame();
    if (!jpeg) return;
    sendJson({ type: "frame", jpeg });
    stats.framesSent += 1;
  }

  function startFrames() {
    if (frameTimer === null) frameTimer = timers.setInterval(sendFrame, frameIntervalMs);
  }
  function stopFrames() {
    if (frameTimer !== null) timers.clearInterval(frameTimer);
    frameTimer = null;
  }
  function dropSocket(code) {
    const s = socket;
    socket = null;
    ready = false;
    if (!s) return;
    s.onopen = s.onmessage = s.onclose = s.onerror = null;
    try { s.close(code); } catch { /* 이미 닫힘 */ }
  }

  // 마이크·사진·재생·재연결을 모두 멈춘다.
  function sendPing() {
    if (ready && !closed && isOpen()) sendJson({ type: "ping" }); // 숨김 중에도 보낸다
  }

  function stopAll(code) {
    closed = true;
    stopFrames();
    if (pingTimer !== null) timers.clearInterval(pingTimer);
    pingTimer = null;
    if (retryTimer !== null) timers.clearTimeout(retryTimer);
    retryTimer = null;
    player.stop();
    mic.stop();
    dropSocket(code);
  }

  // ── ready 뒤 끊김: 자동 재연결 ──────────────────────────────────────────
  function startReconnect(reason) {
    if (closed || linkDown) return;
    linkDown = true;
    attempt = 0;
    stopFrames();
    player.stop();
    transcript?.end();
    dropSocket();
    emit("reconnecting");
    scheduleRetry(reason);
  }
  function scheduleRetry(reason) {
    const delay = Math.min(RECONNECT_FIRST_MS * 2 ** Math.min(attempt, 10), RECONNECT_MAX_GAP_MS);
    attempt += 1;
    retryTimer = timers.setTimeout(() => {
      retryTimer = null;
      tryReconnect(reason);
    }, delay);
  }
  async function tryReconnect(reason) {
    if (closed) return;
    stats.reconnectAttempts += 1;
    attemptInFlight = true;
    try {
      await connect(true, openTimeoutMs);
    } catch (err) {
      if (!closed && linkDown && retryTimer === null) scheduleRetry(err.message || reason);
    } finally {
      attemptInFlight = false;
    }
  }
  // 화면이 다시 보일 때: 기다리던 간격을 버리고 지금 바로 시도한다. 간격도 1초부터 다시.
  function reconnectNow(reason) {
    if (closed) return;
    if (!linkDown) startReconnect(reason);
    if (retryTimer !== null) timers.clearTimeout(retryTimer);
    retryTimer = null;
    attempt = 0;
    if (!attemptInFlight) tryReconnect(reason);
  }

  // 소켓 하나를 열고 ready까지 기다린다. ready 뒤의 끊김은 startReconnect로 넘긴다.
  function connect(resume, timeoutMs) {
    return new Promise((resolve, reject) => {
      let settled = false;
      let s = null;
      const timeout = timers.setTimeout(() => settle(new Error("Live did not become ready in time")), timeoutMs);
      function settle(err, data) {
        if (settled) return;
        settled = true;
        timers.clearTimeout(timeout);
        if (err) {
          if (socket === s) dropSocket();
          else try { s?.close(); } catch { /* 이미 닫힘 */ }
          reject(err);
        } else resolve(data);
      }
      try {
        s = new WS(deps.url || defaultUrl());
      } catch (err) {
        settle(err);
        return;
      }
      socket = s;
      s.binaryType = "arraybuffer";
      s.onopen = () => {
        sendJson(resume ? { ...hello, resume: true } : hello);
      };
      s.onmessage = (event) => {
        if (closed || socket !== s) return;
        if (typeof event.data !== "string") {
          if (!ready) return;
          if (state === "listening") emit("speaking");
          player.push(event.data);
          return;
        }
        let data;
        try { data = JSON.parse(event.data); } catch { return; }
        switch (data.type) {
          case "ready":
            ready = true;
            linkDown = false;
            serverReconnecting = false;
            startFrames();
            if (pingTimer === null) pingTimer = timers.setInterval(sendPing, PING_INTERVAL_MS);
            emit(idleState());
            if (everReady) handlers.onReconnected?.(data);
            else handlers.onReady?.(data); // 새로고침 뒤 resume:true로 연 첫 연결도 여기(data.resumed로 구분)
            everReady = true;
            settle(null, data);
            break;
          case "heard":
            transcript?.heard(data.text);
            break;
          case "said":
            transcript?.said(data.text);
            break;
          case "interrupted":
            player.stop(); // 관람객이 말을 끊었다. 남은 답변 소리를 바로 버린다.
            transcript?.end();
            if (!serverReconnecting) emit(idleState());
            break;
          case "turn_complete":
            transcript?.end();
            if (!serverReconnecting) emit(idleState());
            handlers.onTurnComplete?.();
            break;
          // 칸 이름을 여기 적어 두지 않는다. 적어 두면 서버가 보내는 새 칸이 조용히 버려진다 —
          // 11/18에 서버가 보내기 시작한 artist·foreign_* 가 그렇게 사라져서 요약의 비교가 비었다.
          case "artwork":
            handlers.onArtwork?.(data);
            break;
          case "comparison":
            handlers.onComparison?.(data);
            break;
          case "reconnecting":
            serverReconnecting = true;
            emit("reconnecting");
            break;
          case "reconnected":
            serverReconnecting = false;
            transcript?.end();
            emit(idleState());
            break;
          case "error":
            if (!ready) settle(new Error(data.message || "Live error"));
            else startReconnect(data.message || "Live error");
            break;
          default:
            break; // 모르는 메시지는 무시한다(서버가 먼저 새 메시지를 더해도 화면이 멈추지 않게).
        }
      };
      s.onerror = () => { /* onclose가 뒤따른다. 거기서 처리한다. */ };
      s.onclose = (event) => {
        if (closed || socket !== s) return;
        const reason = `Live connection closed (code ${event?.code ?? "?"})`;
        if (!ready) settle(new Error(reason));
        else startReconnect(reason);
      };
    });
  }

  async function resumeAudioInner() {
    let ok = true;
    try { const info = await player.start(); if (info && info.state && info.state !== "running") ok = false; }
    catch { ok = false; }
    try { if (mic.resume && !(await mic.resume())) ok = false; }
    catch { ok = false; }
    return ok;
  }

  return {
    /** 사용자 동작 안에서, 첫 await 전에 부른다(아이폰 Safari). */
    prime() {
      player.start().catch(() => {}); // AudioContext 생성과 resume이 이 줄에서 동기로 시작된다.
      mic.prime();
    },

    /**
     * 처음 연결. ready까지 기다린다. 실패하면 거절된다(부른 쪽이 기존 방식으로 대체).
     * resume: true는 새로고침 뒤 같은 관람을 이을 때(첫 메시지에 resume:true).
     */
    async open({ sessionId, profile, stream, resume = false }) {
      emit("connecting");
      hello = { mode: "handsfree", session_id: sessionId || "", profile: profile || {} };
      try {
        await mic.start(stream, onMicChunk);
        return await connect(Boolean(resume), openTimeoutMs);
      } catch (err) {
        stopAll();
        throw err;
      }
    },

    /** 글로 묻기. 보냈으면 true. 재연결 중이면 false(부른 쪽이 기존 방식으로 보낸다). */
    sendText(text) {
      const value = String(text || "").trim();
      if (!value || !ready || closed || linkDown) return false;
      if (!sendJson({ type: "text", text: value })) return false;
      player.stop(); // 새 질문이 앞 답변을 끊는다(말로 끊을 때와 같게).
      transcript?.typed(value);
      return true;
    },

    /** 음소거: 무음 600ms를 보낸 뒤 마이크 PCM을 보내지 않는다. 사진과 답변 재생은 계속한다. */
    setMuted(value) {
      const next = Boolean(value);
      if (next && !muted) silenceLeft = Math.ceil(MUTE_SILENCE_MS / CHUNK_MS);
      if (!next) silenceLeft = 0;
      muted = next;
      if (!serverReconnecting && !linkDown && ready) emit(idleState());
      return muted;
    },
    toggleMuted() { return this.setMuted(!muted); },

    /**
     * 페이지가 보이는지(document.visibilityState). 숨겨지면 마이크·사진 전송만 멈춘다(소켓은 둔다).
     * 다시 보이면: 소리 장치 resume(안 되면 onNeedsTap), 마이크 트랙이 끝났으면 다시 얻기,
     * 소켓이 죽었으면 재연결, 살아 있으면 전송 재개.
     */
    async setVisible(visible) {
      if (closed) return;
      if (!visible) {
        hidden = true;
        if (!linkDown) emit("paused");
        return;
      }
      hidden = false;
      if (!(await resumeAudioInner())) {
        needsTap = true;
        handlers.onNeedsTap?.();
      }
      if (closed) return;
      if (mic.trackEnded?.()) {
        try {
          const fresh = await getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
          mic.restart(fresh);
          handlers.onMicStream?.(fresh);
        } catch { /* 권한·장치 문제. 글 질문은 계속 된다. */ }
      }
      if (closed) return;
      const dead = !socket || socket.readyState >= 2;
      if (linkDown || dead) reconnectNow("socket closed while hidden");
      else emit(idleState());
    },

    /** "Tap to resume" 버튼에서 부른다(사용자 동작 안). */
    async resumeAudio() {
      const ok = await resumeAudioInner();
      if (ok) needsTap = false;
      if (!closed && !linkDown && ready) emit(idleState());
      return ok;
    },

    /** END VISIT 등. 마이크·사진·재생을 멈추고 소켓을 닫는다. onFallback은 부르지 않는다. */
    close() {
      if (closed) return;
      stopAll(1000);
    },

    get muted() { return muted; },
    get needsTap() { return needsTap; },
    get ready() { return ready && !closed; },
    get reconnecting() { return linkDown && !closed; },
    get state() { return state; },
    get stats() { return { ...stats }; },
  };
}
