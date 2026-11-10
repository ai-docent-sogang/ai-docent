// api.js가 docs/api.md대로 요청을 보내는지 확인한다(서버 없이 fetch만 가로챈다).
//
// 담당: FE1
// 실행: node tests/test_ask.mjs   (저장소 어디서 실행해도 된다)

import assert from "node:assert";

let seen = null;
globalThis.fetch = async (u, opts) => {
  seen = { u, opts };
  return { ok: true, status: 200, json: async () => ({ answer: "A", status: "ok" }) };
};

const { postAsk } = await import(new URL("../static/api.js", import.meta.url));
const out = await postAsk({ artworkId: "KHD_SSIREUM", question: "Who painted this?" });

assert.equal(seen.u, "/api/ask", "주소");
assert.equal(seen.opts.method, "POST");
assert.equal(seen.opts.headers["Content-Type"], "application/json");
assert.deepEqual(JSON.parse(seen.opts.body), { artwork_id: "KHD_SSIREUM", question: "Who painted this?" });
assert.equal(out.answer, "A");

// 오류 응답은 예외로 올라와야 한다
globalThis.fetch = async () => ({ ok: false, status: 400, text: async () => "question is required" });
await assert.rejects(() => postAsk({ artworkId: "X", question: "" }), /400/);

// config.js의 작품 ID가 CSV에 있는 것인지는 별도로 확인한다
const { ARTWORKS, DEFAULT_ARTWORK_ID } = await import(new URL("../static/config.js", import.meta.url));
assert.ok(ARTWORKS.some((a) => a.id === DEFAULT_ARTWORK_ID), "기본 작품이 목록에 있어야 한다");
console.log("api.js postAsk 검사 통과 · 작품", ARTWORKS.length, "점");
