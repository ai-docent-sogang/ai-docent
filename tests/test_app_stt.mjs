// app.js의 음성 입력 버튼(③ STT)을 모의 DOM에서 확인한다.
//
// 담당: FE1
// 실행: node tests/test_app_stt.mjs
// 확인하는 것: 버튼을 누르면 듣기 시작, 중간 결과가 입력창에 흐리게 들어가는지, 최종 결과가 남는지,
//              오류마다 안내 문장이 바뀌는지, 한 번 더 누르면 멈추는지, 보내기는 기존 흐름을 쓰는지.
import assert from "node:assert";

const listeners = new Map();
const nodes = new Map();
const madeRecognitions = [];

class FakeRecognition {
  constructor() { madeRecognitions.push(this); }
  start() {}
  stop() { this.onend?.(); } // 브라우저는 stop() 뒤 onend를 부른다
  emit(text, isFinal) { this.onresult({ results: [Object.assign([{ transcript: text }], { isFinal })] }); }
  // 규격: error 이벤트 뒤에 end 이벤트가 따라온다. 그 순서를 그대로 흉내 낸다.
  fail(error) { this.onerror({ error }); this.onend(); }
}

function makeNode(id) {
  const classes = new Set();
  return {
    id, children: [], value: "", textContent: "", disabled: false, href: "",
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      has: (c) => classes.has(c),
    },
    addEventListener: (type, fn) => listeners.set(`${id}:${type}`, fn),
    appendChild: (c) => c, append: () => {},
    scrollTop: 0, scrollHeight: 0,
  };
}
const getNode = (id) => { if (!nodes.has(id)) nodes.set(id, makeNode(id)); return nodes.get(id); };

globalThis.document = { getElementById: getNode, createElement: () => makeNode("created") };
globalThis.window = { SpeechRecognition: FakeRecognition, speechSynthesis: { cancel() {}, getVoices: () => [], speak() {} } };
globalThis.speechSynthesis = globalThis.window.speechSynthesis;
globalThis.SpeechSynthesisUtterance = globalThis.window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
globalThis.performance = { now: () => 0 };
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ answer: "A", status: "ok", artwork_id: "X", artwork_title: "X", source_url: "", latency_ms: 1, model: "m" }) });

await import(new URL("../static/app.js", import.meta.url));

const btn = getNode("ask-listen");
const input = getNode("ask-input");
const status = getNode("ask-stt-status");
const click = listeners.get("ask-listen:click");
assert.ok(click, "음성 입력 버튼에 핸들러가 있어야 한다");
assert.equal(btn.disabled, false, "지원하는 브라우저에서는 버튼이 켜져 있어야 한다");

// ① 누르면 듣기 시작
click();
assert.equal(madeRecognitions.length, 1, "인식기가 하나 만들어져야 한다");
assert.ok(btn.classList.has("listening"), "버튼이 듣는 상태로 보여야 한다");
assert.equal(status.textContent, "Listening…");

// ② 중간 결과는 흐리게, 최종 결과는 그대로
const r = madeRecognitions[0];
r.emit("who painted", false);
assert.equal(input.value, "who painted");
assert.ok(input.classList.has("partial"), "중간 결과는 흐리게 표시한다");
r.emit("Who painted this?", true);
r.onend();
assert.equal(input.value, "Who painted this?");
assert.ok(!input.classList.has("partial"), "최종 결과는 흐리게 두지 않는다");
assert.ok(status.textContent.includes("tap Ask"), status.textContent);
assert.ok(!btn.classList.has("listening"), "끝나면 버튼이 돌아와야 한다");

// ③ 마이크 거부는 안내가 달라진다
click();
madeRecognitions.at(-1).fail("not-allowed");
assert.ok(status.textContent.includes("Microphone blocked"), status.textContent);
assert.ok(!btn.classList.has("listening"), "오류 뒤에는 버튼이 돌아와야 한다");

// ④ 듣는 중에 한 번 더 누르면 멈춘다 (인식기를 새로 만들지 않는다)
const count = madeRecognitions.length;
click();                       // 시작
assert.equal(madeRecognitions.length, count + 1);
click();                       // 멈춤
assert.equal(madeRecognitions.length, count + 1, "멈출 때는 새 인식기를 만들지 않는다");
assert.ok(!btn.classList.has("listening"));

// ⑤ 말이 없으면 안내하고, 입력창은 그대로 둔다
click();
input.value = "";
madeRecognitions.at(-1).onend();
assert.ok(status.textContent.includes("did not catch"), status.textContent);

// ⑥ 보내기는 기존 ask-form 흐름을 그대로 쓴다
input.value = "Who painted this?";
await listeners.get("ask-form:submit")({ preventDefault() {} });
const log = getNode("log").children;
assert.ok(getNode("ask-meta").textContent.includes("status ok"), getNode("ask-meta").textContent);

console.log("app.js 음성 입력 검사 통과 (듣기 시작·중간·최종 결과, 마이크 거부, 다시 눌러 멈춤, 무음, 보내기 연결)");
