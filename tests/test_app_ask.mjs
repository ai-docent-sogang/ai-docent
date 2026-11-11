// app.js의 /api/ask 흐름을 모의 DOM에서 확인한다. 브라우저 없이 돌아간다.
//
// 담당: FE1
// 실행: node tests/test_app_ask.mjs
// 확인하는 것: 질문이 말풍선에 들어가는지, 답변을 음성으로 읽어 주는지, status·시간·출처가 표시되는지,
//              빈 질문을 막는지, 오류가 화면에 보이는지, 기존 /api/turn 핸들러가 남아 있는지.

import assert from "node:assert";

const listeners = new Map();   // "id:type" → 함수
const nodes = new Map();       // id → 가짜 요소
const spoken = [];             // speak()로 읽어 준 문장

function makeNode(id) {
  const children = [];
  const node = {
    id, children, value: "", textContent: "", disabled: false, href: "", target: "", rel: "",
    className: "", srcObject: null, videoWidth: 0,
    classList: { add() {}, remove() {} },
    addEventListener: (type, fn) => listeners.set(`${id}:${type}`, fn),
    appendChild: (c) => { children.push(c); return c; },
    append: (...xs) => children.push(...xs),
    scrollTop: 0, scrollHeight: 0,
  };
  return node;
}
const getNode = (id) => { if (!nodes.has(id)) nodes.set(id, makeNode(id)); return nodes.get(id); };

globalThis.document = {
  getElementById: getNode,
  createElement: () => makeNode("created"),
};
globalThis.window = {};
globalThis.performance = { now: () => 0 };
// navigator는 Node에서 읽기 전용이라 app.js가 쓰는 부분만 덮어쓴다
try { globalThis.navigator.mediaDevices ??= {}; } catch {}
globalThis.window.speechSynthesis = globalThis.speechSynthesis = {
  cancel() {}, getVoices: () => [], speak: (u) => spoken.push(u.text),
};
globalThis.window.SpeechSynthesisUtterance = globalThis.SpeechSynthesisUtterance = class {
  constructor(text) { this.text = text; }
};

let reply = {
  answer: "Kim Hong-do painted this.", artwork_id: "KHD_SSIREUM",
  artwork_title: "Korean Traditional Wrestling", status: "ok",
  source_url: "https://www.emuseum.go.kr/detail?relicId=X", latency_ms: 1234, model: "gemini-flash-latest",
};
let calls = 0;
globalThis.fetch = async () => { calls += 1; return { ok: true, status: 200, json: async () => reply }; };

await import(new URL("../static/app.js", import.meta.url));

// 작품 목록이 채워졌고 기본값이 선택됐다
const select = getNode("ask-artwork");
assert.equal(select.children.length, 11, "작품 11점이 목록에 들어가야 한다");
assert.equal(select.value, "KHD_SSIREUM");

// 질문 보내기
const submit = listeners.get("ask-form:submit");
assert.ok(submit, "ask-form submit 핸들러가 등록되어야 한다");
getNode("ask-input").value = "Who painted this?";
await submit({ preventDefault() {} });

const log = getNode("log").children.map((c) => `${c.className}=${c.textContent}`);
assert.deepEqual(log, ["msg visitor=Who painted this?", "msg docent=Kim Hong-do painted this."], log.join(" / "));
assert.deepEqual(spoken, ["Kim Hong-do painted this."], "답변을 음성으로 읽어야 한다");
assert.equal(getNode("ask-input").value, "", "보낸 뒤 입력창은 비워야 한다");

const meta = getNode("ask-meta").textContent;
for (const want of ["Korean Traditional Wrestling", "status ok", "server 1234 ms", "model gemini-flash-latest"]) {
  assert.ok(meta.includes(want), `ask-meta에 "${want}"가 있어야 한다. 실제: ${meta}`);
}
assert.ok(getNode("ask-meta").children.some((c) => typeof c === "object" && c.href?.includes("emuseum")), "출처 링크가 붙어야 한다");
assert.equal(getNode("replay").disabled, false, "답변을 받았으면 Replay를 쓸 수 있어야 한다");

// 빈 질문은 보내지 않는다
const before = calls;
getNode("ask-input").value = "   ";
await submit({ preventDefault() {} });
assert.equal(calls, before, "빈 질문은 서버로 보내지 않아야 한다");

// mock 상태면 안내가 붙는다
reply = { ...reply, status: "mock", model: "", source_url: "" };
getNode("ask-input").value = "Test";
await submit({ preventDefault() {} });
assert.ok(getNode("ask-meta").textContent.includes("임시 답변"), getNode("ask-meta").textContent);

// 서버에 닿지 못하면 화면에 오류가 보인다
globalThis.fetch = async () => ({ ok: false, status: 500, text: async () => "boom" });
getNode("ask-input").value = "Test";
await submit({ preventDefault() {} });
assert.ok(getNode("ask-meta").textContent.startsWith("Error: 500"), getNode("ask-meta").textContent);

// 기존 /api/turn 흐름의 핸들러가 그대로 남아 있다
for (const key of ["start:click", "text-form:submit", "talk:pointerdown", "test-voice:click", "replay:click"]) {
  assert.ok(listeners.has(key), `${key} 핸들러가 남아 있어야 한다`);
}
console.log("app.js /api/ask 흐름 검사 통과 (말풍선·음성·status·출처·빈 질문·오류·기존 흐름 보존)");
