// live_conversation.js(버튼 없는 Live 대화)를 서버·브라우저 없이 확인한다.
//
// 담당: FE1
// 실행: node tests/test_live_conversation.mjs
// 확인하는 것: 첫 메시지 형식(mode·session_id·profile), ready 뒤에만 마이크 PCM 전송·음소거,
//              heard/said 조각 이어 붙이기와 turn_complete에서 끊기, interrupted에서 재생 즉시 멈춤,
//              artwork/comparison 전달, 3초 주기 사진 전송, 글 질문, error·끊김에서 대체 경로 신호,
//              ready 전 실패·시간 초과에서 open() 거절, close()가 마이크·사진·재생·소켓을 모두 멈추는지.
import assert from "node:assert";

const { createLiveConversation, FRAME_INTERVAL_MS } = await import(
  new URL("../static/live_conversation.js", import.meta.url)
);

// ── 가짜들 ──────────────────────────────────────────────────────────────────────
class FakeSocket {
  static last = null;
  constructor(url) {
    this.url = url; this.readyState = 0; this.sent = []; this.closedWith = null;
    FakeSocket.last = this;
  }
  send(data) { this.sent.push(data); }
  close(code) { this.closedWith = code ?? 1005; this.readyState = 3; }
  // 시험이 부르는 것
  serverOpen() { this.readyState = 1; this.onopen?.(); }
  serverSend(obj) { this.onmessage?.({ data: typeof obj === "string" || obj instanceof ArrayBuffer ? obj : JSON.stringify(obj) }); }
  serverClose(code = 1011) { this.readyState = 3; this.onclose?.({ code }); }
  json() { return this.sent.filter((d) => typeof d === "string").map((d) => JSON.parse(d)); }
  binary() { return this.sent.filter((d) => d instanceof ArrayBuffer); }
}

function fakePlayer() {
  return {
    started: 0, pushed: [], stops: 0,
    async start() { this.started += 1; return { sampleRate: 48000, state: "running" }; },
    push(buf) { this.pushed.push(buf); },
    stop() { this.stops += 1; this.pushed = []; },
  };
}

function fakeMic() {
  return {
    primed: 0, stopped: 0, onChunk: null, fail: false,
    prime() { this.primed += 1; },
    async start(stream, onChunk) { if (this.fail) throw new Error("AudioWorklet unavailable"); this.onChunk = onChunk; },
    stop() { this.stopped += 1; },
    speak() { this.onChunk?.(new Int16Array(1600)); }, // 100ms 조각 하나
  };
}

// 직접 돌리는 타이머. tick(ms)만큼 시간을 보낸다.
function fakeTimers() {
  let now = 0, id = 0;
  const jobs = new Map();
  return {
    setInterval(fn, ms) { jobs.set(++id, { fn, ms, at: now + ms, every: true }); return id; },
    setTimeout(fn, ms) { jobs.set(++id, { fn, ms, at: now + ms, every: false }); return id; },
    clearInterval(i) { jobs.delete(i); },
    clearTimeout(i) { jobs.delete(i); },
    tick(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        for (const [k, j] of jobs) if (j.at <= end && (!next || j.at < next[1].at)) next = [k, j];
        if (!next) break;
        const [k, j] = next;
        now = j.at;
        if (j.every) j.at += j.ms; else jobs.delete(k);
        j.fn();
      }
      now = end;
    },
    get active() { return jobs.size; },
  };
}

// 말풍선이 붙는 #log 흉내
function fakeLog() {
  const log = { children: [], scrollTop: 0, scrollHeight: 100, appendChild(el) { this.children.push(el); return el; } };
  const doc = { createElement: (tag) => ({ tag, className: "", textContent: "" }) };
  return { log, doc, bubbles: () => log.children.map((c) => [c.className, c.textContent]) };
}

function setup(extra = {}) {
  const player = fakePlayer(), mic = fakeMic(), timers = fakeTimers(), { log, doc, bubbles } = fakeLog();
  const events = { status: [], artwork: [], comparison: [], fallback: [], ready: [], turns: 0 };
  let frameNo = 0;
  const conv = createLiveConversation({
    log, doc, player, mic, timers,
    WebSocketImpl: FakeSocket, url: "ws://test/ws/live",
    captureFrame: () => (extra.noVideo ? null : `JPEG${++frameNo}`),
    handlers: {
      onStatus: (s) => events.status.push(s.state),
      onReady: (d) => events.ready.push(d),
      onArtwork: (d) => events.artwork.push(d),
      onComparison: (d) => events.comparison.push(d),
      onFallback: (r) => events.fallback.push(r),
      onTurnComplete: () => { events.turns += 1; },
    },
    ...extra.deps,
  });
  return { conv, player, mic, timers, events, bubbles };
}

const PROFILE = { country: "europe", age_group: "20-29", language: "en" };

async function openReady(t) {
  t.conv.prime();
  const opened = t.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve(); // mic.start를 기다린다
  const ws = FakeSocket.last;
  ws.serverOpen();
  ws.serverSend({ type: "ready", model: "m", mode: "handsfree", session_id: "S1" });
  await opened;
  return ws;
}

// ① 연결: prime, 첫 메시지, ready 전에는 마이크를 보내지 않음
{
  const t = setup();
  t.conv.prime();
  assert.equal(t.player.started, 1, "prime()이 재생 AudioContext를 깨워야 한다(사용자 동작 안)");
  assert.equal(t.mic.primed, 1, "prime()이 마이크 AudioContext를 만들어야 한다");
  const opened = t.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve();
  const ws = FakeSocket.last;
  assert.equal(ws.url, "ws://test/ws/live");
  assert.equal(ws.binaryType, "arraybuffer");
  ws.serverOpen();
  assert.deepEqual(ws.json()[0], { mode: "handsfree", session_id: "S1", profile: PROFILE }, "첫 메시지는 계약 형식 그대로");
  assert.ok(!("artwork_id" in ws.json()[0]), "handsfree 첫 메시지에 artwork_id는 없다");
  t.mic.speak();
  assert.equal(ws.binary().length, 0, "ready 전 마이크 소리는 보내지 않는다");
  ws.serverSend({ type: "ready", model: "m", mode: "handsfree", session_id: "S1" });
  const ready = await opened;
  assert.equal(ready.session_id, "S1");
  assert.equal(t.events.ready.length, 1);
  assert.equal(t.conv.state, "listening");
  console.log("  ① 첫 메시지 형식, ready 전 마이크 차단, ready에서 listening");
}

// ② 마이크 계속 전송, 음소거·해제
{
  const t = setup();
  const ws = await openReady(t);
  for (let i = 0; i < 5; i++) t.mic.speak(); // 말이 없을 때도 조각은 계속 온다
  assert.equal(ws.binary().length, 5, "ready 뒤에는 조각마다 바이너리로 보낸다");
  assert.equal(ws.binary()[0].byteLength, 3200, "1600샘플 × 2바이트 = 16kHz PCM16 100ms");
  t.conv.toggleMuted();
  assert.equal(t.conv.muted, true);
  assert.equal(t.conv.state, "muted");
  t.mic.speak(); t.mic.speak();
  assert.equal(ws.binary().length, 5, "음소거 중에는 보내지 않는다");
  t.conv.setMuted(false);
  t.mic.speak();
  assert.equal(ws.binary().length, 6, "음소거를 풀면 다시 보낸다");
  assert.equal(t.conv.state, "listening");
  console.log("  ② 마이크 PCM 계속 전송, 음소거 중 전송 멈춤·해제 후 재개");
}

// ③ heard/said 이어 붙이기, 답변 음성 재생, turn_complete
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend({ type: "heard", text: "Who " });
  ws.serverSend({ type: "heard", text: "painted this?" });
  ws.serverSend(new Int16Array(2400).buffer);
  assert.equal(t.conv.state, "speaking", "답변 소리가 오면 speaking");
  ws.serverSend({ type: "said", text: "Kim Hong-do " });
  ws.serverSend({ type: "said", text: "painted it." });
  ws.serverSend(new Int16Array(2400).buffer);
  assert.equal(t.player.pushed.length, 2, "답변 음성 조각을 재생 줄에 넣는다");
  assert.deepEqual(t.bubbles(), [["msg visitor", "Who painted this?"], ["msg docent", "Kim Hong-do painted it."]],
    "같은 턴의 조각은 같은 말풍선에 이어 붙는다");
  ws.serverSend({ type: "turn_complete" });
  assert.equal(t.events.turns, 1);
  assert.equal(t.conv.state, "listening");
  ws.serverSend({ type: "heard", text: "And the date?" });
  ws.serverSend({ type: "said", text: "Late 18th century." });
  assert.equal(t.bubbles().length, 4, "turn_complete 뒤 조각은 새 말풍선");
  assert.deepEqual(t.bubbles()[2], ["msg visitor", "And the date?"]);
  console.log("  ③ heard/said 조각 이어 붙이기, 재생, turn_complete 뒤 새 말풍선");
}

// ④ interrupted: 재생 즉시 멈춤, 다음 말은 새 말풍선
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend({ type: "heard", text: "Tell me" });
  ws.serverSend({ type: "said", text: "This painting shows" });
  ws.serverSend(new Int16Array(2400).buffer);
  ws.serverSend(new Int16Array(2400).buffer);
  const stopsBefore = t.player.stops;
  ws.serverSend({ type: "interrupted" });
  assert.equal(t.player.stops, stopsBefore + 1, "interrupted에서 player.stop()을 바로 부른다");
  assert.equal(t.player.pushed.length, 0, "남은 답변 소리가 버려진다");
  ws.serverSend({ type: "heard", text: "Wait, who" });
  assert.equal(t.bubbles().length, 3, "끊은 뒤의 말은 새 관람객 말풍선");
  console.log("  ④ interrupted에서 재생 즉시 멈춤, 새 말풍선");
}

// ⑤ artwork / comparison 전달
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend({ type: "artwork", artwork_id: "KHD_SSIREUM", artwork_title: "Ssireum" });
  ws.serverSend({ type: "comparison", comparison_id: "C_KHD_BRUEGEL", artwork_id: "KHD_SSIREUM" });
  ws.serverSend({ type: "something_new" }); // 모르는 메시지는 무시
  assert.deepEqual(t.events.artwork, [{ artwork_id: "KHD_SSIREUM", artwork_title: "Ssireum" }]);
  assert.deepEqual(t.events.comparison, [{ artwork_id: "KHD_SSIREUM", comparison_id: "C_KHD_BRUEGEL" }]);
  console.log("  ⑤ artwork·comparison을 recordArtwork 형식으로 전달, 모르는 메시지 무시");
}

// ⑥ 사진 주기: 3초마다, ready 전에는 없음, 영상 없으면 건너뜀
{
  const t = setup();
  t.conv.prime();
  const opened = t.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve();
  const ws = FakeSocket.last;
  ws.serverOpen();
  t.timers.tick(5000);
  assert.equal(ws.json().filter((m) => m.type === "frame").length, 0, "ready 전에는 사진을 보내지 않는다");
  ws.serverSend({ type: "ready", model: "m" });
  await opened;
  assert.equal(FRAME_INTERVAL_MS, 3000);
  t.timers.tick(2999);
  assert.equal(ws.json().filter((m) => m.type === "frame").length, 0, "3초가 되기 전에는 보내지 않는다");
  t.timers.tick(1);
  t.timers.tick(6000);
  const frames = ws.json().filter((m) => m.type === "frame");
  assert.deepEqual(frames.map((f) => f.jpeg), ["JPEG1", "JPEG2", "JPEG3"], "3초마다 하나씩");
  assert.deepEqual(Object.keys(frames[0]).sort(), ["jpeg", "type"]);

  const noVideo = setup({ noVideo: true });
  const ws2 = await openReady(noVideo);
  noVideo.timers.tick(9000);
  assert.equal(ws2.json().filter((m) => m.type === "frame").length, 0, "영상이 없으면 보내지 않는다");
  console.log("  ⑥ 사진 3초 주기, ready 전·영상 없을 때 건너뜀");
}

// ⑦ 글 질문
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend(new Int16Array(2400).buffer);
  assert.equal(t.conv.sendText("  What is this?  "), true);
  assert.deepEqual(ws.json().at(-1), { type: "text", text: "What is this?" });
  assert.equal(t.player.pushed.length, 0, "새 질문은 앞 답변 소리를 멈춘다");
  assert.deepEqual(t.bubbles().at(-1), ["msg visitor", "What is this?"], "글 질문은 화면이 직접 말풍선을 만든다");
  ws.serverSend({ type: "said", text: "A wrestling match." });
  assert.deepEqual(t.bubbles().at(-1), ["msg docent", "A wrestling match."]);
  assert.equal(t.conv.sendText("   "), false, "빈 글은 보내지 않는다");
  console.log("  ⑦ 글 질문 {type:text}, 말풍선, 재생 멈춤");
}

// ⑧ 재연결 표시
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend({ type: "reconnecting" });
  assert.equal(t.conv.state, "reconnecting");
  ws.serverSend({ type: "turn_complete" }); // 서버가 옮기기 전에 턴을 닫아 준다
  assert.equal(t.conv.state, "reconnecting", "재연결 중에는 상태를 유지한다");
  ws.serverSend({ type: "reconnected", kept_conversation: true });
  assert.equal(t.conv.state, "listening");
  assert.equal(t.events.fallback.length, 0, "재연결은 대체 경로 신호가 아니다");
  console.log("  ⑧ reconnecting/reconnected 상태 표시");
}

// ⑨ ready 뒤 error → 대체 경로 신호, 모두 정지
{
  const t = setup();
  const ws = await openReady(t);
  const active = t.timers.active;
  assert.ok(active >= 1, "사진 타이머가 돌고 있어야 한다");
  ws.serverSend({ type: "error", message: "Gemini failed" });
  assert.deepEqual(t.events.fallback, ["Gemini failed"], "error면 onFallback으로 알린다");
  assert.equal(t.mic.stopped, 1, "마이크를 멈춘다");
  assert.equal(t.timers.active, 0, "사진 전송을 멈춘다");
  assert.ok(ws.closedWith !== null, "소켓을 닫는다");
  assert.equal(t.conv.ready, false);
  t.mic.speak();
  assert.equal(ws.binary().length, 0, "대체된 뒤에는 아무것도 보내지 않는다");
  assert.equal(t.conv.sendText("hi"), false, "대체된 뒤 글은 기존 방식으로 가도록 false");
  ws.serverClose(1011);
  assert.equal(t.events.fallback.length, 1, "신호는 한 번만");
  console.log("  ⑨ ready 뒤 error → onFallback 한 번, 마이크·사진·소켓 정지");
}

// ⑩ ready 뒤 갑자기 끊김 → 대체 경로 신호
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverClose(1006);
  assert.equal(t.events.fallback.length, 1);
  assert.match(t.events.fallback[0], /1006/);
  console.log("  ⑩ ready 뒤 끊김 → onFallback");
}

// ⑪ ready 전 실패: error 메시지(지금 서버는 artwork_id가 없으면 "unknown artwork"), 끊김, 시간 초과, 마이크 실패
{
  const t = setup();
  t.conv.prime();
  const opened = t.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve();
  FakeSocket.last.serverOpen();
  FakeSocket.last.serverSend({ type: "error", message: "unknown artwork" });
  await assert.rejects(opened, /unknown artwork/);
  assert.equal(t.events.fallback.length, 0, "ready 전 실패는 open() 거절로만 알린다");
  assert.equal(t.mic.stopped, 1, "마이크를 멈춘다");
  assert.equal(t.timers.active, 0, "시간 초과 타이머도 지운다");

  const c = setup();
  const o2 = c.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve();
  FakeSocket.last.serverClose(1006);
  await assert.rejects(o2, /closed/);

  const d = setup();
  const o3 = d.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} });
  await Promise.resolve();
  FakeSocket.last.serverOpen(); // 연결은 됐지만 ready가 오지 않는다
  d.timers.tick(12000);
  await assert.rejects(o3, /ready in time/);
  assert.ok(FakeSocket.last.closedWith !== null, "시간 초과면 소켓을 닫는다");

  const e = setup();
  e.mic.fail = true;
  await assert.rejects(e.conv.open({ sessionId: "S1", profile: PROFILE, stream: {} }), /AudioWorklet/);
  console.log("  ⑪ ready 전 error·끊김·12초 시간 초과·마이크 실패 → open() 거절");
}

// ⑫ close(): 모두 멈추고 대체 신호는 보내지 않음
{
  const t = setup();
  const ws = await openReady(t);
  ws.serverSend(new Int16Array(2400).buffer);
  t.conv.close();
  assert.equal(ws.closedWith, 1000, "정상 종료 코드로 닫는다");
  assert.equal(t.mic.stopped, 1);
  assert.equal(t.timers.active, 0, "사진 전송 정지");
  assert.equal(t.player.pushed.length, 0, "재생 정지");
  t.mic.speak();
  t.timers.tick(9000);
  assert.equal(ws.binary().length, 0, "닫은 뒤 마이크를 보내지 않는다");
  assert.equal(ws.json().filter((m) => m.type === "frame").length, 0, "닫은 뒤 사진을 보내지 않는다");
  ws.serverClose(1000);
  ws.serverSend({ type: "said", text: "late" });
  assert.equal(t.events.fallback.length, 0, "직접 닫은 것은 대체 신호가 아니다");
  t.conv.close(); // 두 번 불러도 괜찮다
  console.log("  ⑫ close()가 마이크·사진·재생·소켓을 멈춤, 대체 신호 없음");
}

console.log("live_conversation.js 검사 통과");
