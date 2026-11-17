// AIVY 화면에서 버튼 없이 Live로 대화하는 부분("handsfree" 모드).
//
// 담당: FE1
// 같이 보는 파일: app.js (FE2 화면. 이 파일을 열고 닫고, 실패하면 기존 /api/turn 방식으로 되돌아감),
//               live_mic_worklet.js (마이크 16kHz PCM), live_player.js (답변 24kHz PCM 재생),
//               live_test.js (같은 서버와 push 모드로 대화하는 시험 페이지. 아이폰 제약의 근거),
//               server/live.py (WS /ws/live, T1), 메시지 형식은 '버튼 없는 대화 계약'(2026-11-18)
//
// 하는 일:
//   - WS /ws/live를 열고 첫 메시지로 {mode:"handsfree", session_id, profile}을 보낸다.
//   - 마이크를 말이 없을 때도 계속 16kHz PCM16으로 보낸다. 말의 시작·끝은 서버·Gemini의 자동 음성
//     감지가 판단한다. 음소거하면 보내지 않는다.
//   - 답변 음성(24kHz PCM)을 이어 재생하고, interrupted가 오면 즉시 멈춘다(관람객이 말을 끊음).
//   - 3초마다 카메라 사진(JPEG, 가로 최대 768px, 화질 0.7)을 base64로 보낸다.
//   - heard/said 조각을 말풍선에 이어 붙이고 turn_complete에서 끝낸다.
//   - artwork/comparison은 handlers로 넘긴다(app.js가 요약·상세에 기록).
//   - ready 전에 실패하면 open()이 거절된다. ready 뒤에 error가 오거나 연결이 끊기면
//     handlers.onFallback을 부른다. 둘 다 app.js가 기존 버튼 방식으로 되돌아가는 신호다.
//
// 아이폰 Safari 주의: AudioContext는 사용자가 누른 흐름 안에서, 첫 await 전에 만들어야 한다.
// 그래서 prime()을 따로 두었다. START EXPLORING 처리의 맨 앞에서 부른다(live_test.js와 같은 이유).
// 카메라 사진과 음성은 보내기만 하고 저장하지 않는다(AGENTS.md).

import { createPlayer } from "./live_player.js";

export const FRAME_INTERVAL_MS = 3000;
export const FRAME_MAX_WIDTH = 768;
export const FRAME_QUALITY = 0.7;
// ready가 이 시간 안에 오지 않으면 실패로 본다. 화면이 멈춘 것처럼 보이지 않게 기존 방식으로 넘어간다.
export const OPEN_TIMEOUT_MS = 12000;

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
  return {
    prime() {
      if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume(); // await하지 않는다. 사용자 동작 안에서 부르는 것이 중요하다.
    },
    async start(stream, onChunk) {
      if (!window.AudioWorklet || !ctx) throw new Error("AudioWorklet unavailable");
      const track = stream?.getAudioTracks?.()[0];
      if (!track) throw new Error("no microphone track");
      if (ctx.state === "suspended") await ctx.resume();
      await ctx.audioWorklet.addModule("/static/live_mic_worklet.js");
      node = new AudioWorkletNode(ctx, "mic-downsampler");
      node.port.onmessage = (event) => onChunk(event.data);
      // 관람 시작 때 연 마이크를 그대로 쓴다(아이폰에서 마이크를 두 번 열면 앞의 것이 멈출 수 있다).
      source = ctx.createMediaStreamSource(new MediaStream([track]));
      source.connect(node);
      // 아이폰에서 AudioWorklet이 멈추지 않도록 destination에 붙인다. 소리는 내보내지 않는다.
      const silent = ctx.createGain();
      silent.gain.value = 0;
      node.connect(silent).connect(ctx.destination);
    },
    stop() {
      try { source?.disconnect(); node?.disconnect(); } catch { /* 이미 끊김 */ }
      if (node) node.port.onmessage = null;
      node = source = null;
      if (ctx && ctx.state !== "closed") ctx.close().catch(() => {});
      ctx = null;
    },
  };
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
  reconnecting: { status: "Reconnecting… one moment.", label: "Reconnecting…" },
};

/**
 * handsfree 대화 하나. 부르는 순서: prime()(사용자 동작 안, 첫 await 전) → await open(...) →
 * sendText()/setMuted() → close().
 *
 * handlers: onStatus({state,status,label}), onReady(data), onArtwork(data), onComparison(data),
 *           onTurnComplete(), onFallback(reason)  — 모두 없어도 된다.
 * deps(시험용): WebSocketImpl, player, mic, captureFrame, timers, url, frameIntervalMs, openTimeoutMs, doc
 */
export function createLiveConversation({ handlers = {}, log, video, ...deps } = {}) {
  const WS = deps.WebSocketImpl || globalThis.WebSocket;
  const player = deps.player || createPlayer();
  const mic = deps.mic || createWorkletMic();
  const captureFrame = deps.captureFrame || (() => captureJpegBase64(video));
  const timers = deps.timers || globalThis;
  const frameIntervalMs = deps.frameIntervalMs ?? FRAME_INTERVAL_MS;
  const openTimeoutMs = deps.openTimeoutMs ?? OPEN_TIMEOUT_MS;
  const transcript = log ? createTranscript(log, deps.doc) : null;

  let socket = null;
  let ready = false;
  let closed = false;
  let muted = false;
  let reconnecting = false;
  let frameTimer = null;
  let state = "connecting";
  const stats = { audioChunksSent: 0, framesSent: 0 };

  function emit(next) {
    state = next;
    handlers.onStatus?.({ state: next, ...STATUS[next] });
  }
  const idleState = () => (muted ? "muted" : "listening");
  const isOpen = () => socket && socket.readyState === 1; // WebSocket.OPEN

  function sendJson(obj) {
    if (!isOpen()) return false;
    socket.send(JSON.stringify(obj));
    return true;
  }

  function onMicChunk(pcm) {
    if (!ready || muted || closed || !isOpen()) return;
    socket.send(pcm.buffer);
    stats.audioChunksSent += 1;
  }

  function sendFrame() {
    if (!ready || closed || !isOpen()) return;
    const jpeg = captureFrame();
    if (!jpeg) return;
    sendJson({ type: "frame", jpeg });
    stats.framesSent += 1;
  }

  // 마이크·사진·재생을 모두 멈춘다. 소켓은 부른 쪽에서 닫는다.
  function stopMedia() {
    if (frameTimer !== null) timers.clearInterval(frameTimer);
    frameTimer = null;
    player.stop();
    mic.stop();
  }

  function fail(reason) {
    if (closed) return;
    closed = true;
    ready = false;
    stopMedia();
    try { socket?.close(); } catch { /* 이미 닫힘 */ }
    handlers.onFallback?.(reason);
  }

  return {
    /** 사용자 동작 안에서, 첫 await 전에 부른다(아이폰 Safari). */
    prime() {
      player.start().catch(() => {}); // AudioContext 생성과 resume이 이 줄에서 동기로 시작된다.
      mic.prime();
    },

    /** ready까지 기다린다. ready 전에 실패하면 거절된다(부른 쪽이 기존 방식으로 대체). */
    async open({ sessionId, profile, stream }) {
      emit("connecting");
      try {
        await mic.start(stream, onMicChunk);
      } catch (err) {
        closed = true;
        stopMedia();
        throw err;
      }
      return new Promise((resolve, reject) => {
        let settled = false;
        const settle = (err, data) => {
          if (settled) return;
          settled = true;
          timers.clearTimeout(timeout);
          if (err) {
            closed = true;
            stopMedia();
            try { socket?.close(); } catch { /* 이미 닫힘 */ }
            reject(err);
          } else resolve(data);
        };
        const timeout = timers.setTimeout(() => settle(new Error("Live did not become ready in time")), openTimeoutMs);

        try {
          socket = new WS(deps.url || defaultUrl());
        } catch (err) {
          settle(err);
          return;
        }
        socket.binaryType = "arraybuffer";
        socket.onopen = () => {
          sendJson({ mode: "handsfree", session_id: sessionId || "", profile: profile || {} });
        };
        socket.onmessage = (event) => {
          if (closed) return;
          if (typeof event.data !== "string") {
            if (state !== "speaking" && !muted) emit("speaking");
            player.push(event.data);
            return;
          }
          let data;
          try { data = JSON.parse(event.data); } catch { return; }
          switch (data.type) {
            case "ready":
              ready = true;
              frameTimer = timers.setInterval(sendFrame, frameIntervalMs);
              emit(idleState());
              handlers.onReady?.(data);
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
              emit(idleState());
              break;
            case "turn_complete":
              transcript?.end();
              if (!reconnecting) emit(idleState());
              handlers.onTurnComplete?.();
              break;
            case "artwork":
              handlers.onArtwork?.({ artwork_id: data.artwork_id, artwork_title: data.artwork_title });
              break;
            case "comparison":
              handlers.onComparison?.({ artwork_id: data.artwork_id, comparison_id: data.comparison_id });
              break;
            case "reconnecting":
              reconnecting = true;
              emit("reconnecting");
              break;
            case "reconnected":
              reconnecting = false;
              transcript?.end();
              emit(idleState());
              break;
            case "error":
              if (!ready) settle(new Error(data.message || "Live error"));
              else fail(data.message || "Live error");
              break;
            default:
              break; // 모르는 메시지는 무시한다(서버가 먼저 새 메시지를 더해도 화면이 멈추지 않게).
          }
        };
        socket.onerror = () => { /* onclose가 뒤따른다. 거기서 처리한다. */ };
        socket.onclose = (event) => {
          if (closed) return;
          const reason = `Live connection closed (code ${event?.code ?? "?"})`;
          if (!ready) settle(new Error(reason));
          else fail(reason);
        };
      });
    },

    /** 글로 묻기. 보냈으면 true. */
    sendText(text) {
      const value = String(text || "").trim();
      if (!value || !ready || closed) return false;
      if (!sendJson({ type: "text", text: value })) return false;
      player.stop(); // 새 질문이 앞 답변을 끊는다(말로 끊을 때와 같게).
      transcript?.typed(value);
      return true;
    },

    /** 음소거: 마이크 PCM을 보내지 않는다. 사진과 답변 재생은 계속한다. */
    setMuted(value) {
      muted = Boolean(value);
      if (!reconnecting && ready) emit(idleState());
      return muted;
    },
    toggleMuted() { return this.setMuted(!muted); },

    /** END VISIT 등. 마이크·사진·재생을 멈추고 소켓을 닫는다. onFallback은 부르지 않는다. */
    close() {
      if (closed) return;
      closed = true;
      ready = false;
      stopMedia();
      try { socket?.close(1000, "visit ended"); } catch { /* 이미 닫힘 */ }
    },

    get muted() { return muted; },
    get ready() { return ready && !closed; },
    get state() { return state; },
    get stats() { return { ...stats }; },
  };
}
