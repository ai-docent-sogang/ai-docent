// stt.js(브라우저 음성 인식)를 가짜 SpeechRecognition으로 확인한다. 브라우저 없이 돌아간다.
//
// 담당: FE1
// 실행: node tests/test_stt.mjs
// 확인하는 것: 중간·최종 결과 전달, 말이 없을 때 no-speech, 일부러 멈춘 aborted는 오류가 아님,
//              지원하지 않는 브라우저에서 unsupported, 인식기가 한 번에 하나만 도는지.
import assert from "node:assert";

// 가짜 SpeechRecognition. 테스트가 직접 onresult/onend를 불러 브라우저 동작을 흉내 낸다.
const made = [];
class FakeRecognition {
  constructor() { this.started = false; this.stopped = false; made.push(this); }
  start() { this.started = true; }
  stop() { this.stopped = true; }
  // 아래는 테스트에서 쓰는 보조 함수
  emit(parts) { this.onresult({ results: parts }); }
  finish() { this.onend(); }
}
const result = (transcript, isFinal) => Object.assign([{ transcript }], { isFinal });

globalThis.window = { SpeechRecognition: FakeRecognition };
const { isSupported, listen, stopListening } = await import(new URL("../static/stt.js", import.meta.url));

assert.equal(isSupported(), true);

// ① 중간 결과와 최종 결과
let partials = [], finals = [], errors = [], ends = 0;
listen({
  onPartial: (t) => partials.push(t),
  onFinal: (t) => finals.push(t),
  onError: (c) => errors.push(c),
  onEnd: () => ends++,
});
let r = made.at(-1);
assert.equal(r.started, true, "start()가 불려야 한다");
assert.equal(r.lang, "en-US");
assert.equal(r.continuous, false, "마이크를 계속 열어 두지 않는다");
r.emit([result("who painted", false)]);
assert.deepEqual(partials, ["who painted"], "말하는 중간 결과");
r.emit([result("Who painted this?", true)]);
r.finish();
assert.deepEqual(finals, ["Who painted this?"], "최종 질문 텍스트");
assert.deepEqual(errors, [], "정상일 때 오류는 없다");
assert.equal(ends, 1);

// ② 말이 없으면 no-speech
partials = []; finals = []; errors = []; ends = 0;
listen({ onFinal: (t) => finals.push(t), onError: (c) => errors.push(c), onEnd: () => ends++ });
made.at(-1).finish();
assert.deepEqual(finals, [], "최종 결과가 없어야 한다");
assert.deepEqual(errors, ["no-speech"]);
assert.equal(ends, 1);

// ③ 일부러 멈춘 것(aborted)은 오류로 보지 않는다
errors = [];
listen({ onError: (c) => errors.push(c), onEnd: () => {} });
r = made.at(-1);
r.onerror({ error: "aborted" });
assert.deepEqual(errors, [], "aborted는 오류가 아니다");
r.onerror({ error: "not-allowed" });
assert.deepEqual(errors, ["not-allowed"], "마이크 거부는 오류로 올린다");
r.finish(); // 규격대로 error 뒤에 end가 온다
assert.deepEqual(errors, ["not-allowed"], "end에서 no-speech로 덮어쓰지 않아야 한다");

// ④ 아직 듣고 있는데 새로 시작하면 이전 인식기를 멈춘다(두 개가 동시에 돌지 않게)
listen({ onEnd: () => {} });
const before = made.at(-1); // 끝내지 않은 채로 둔다
listen({ onEnd: () => {} });
assert.equal(before.stopped, true, "듣고 있던 이전 인식기를 멈춰야 한다");
assert.notEqual(made.at(-1), before, "새 인식기를 만들어야 한다");
stopListening();
assert.equal(made.at(-1).stopped, true);

// ⑤ 지원하지 않는 브라우저
const errs = [];
globalThis.window = {}; // SpeechRecognition 없음
const fresh = await import(`${new URL("../static/stt.js", import.meta.url)}?nosupport`);
assert.equal(fresh.isSupported(), false);
fresh.listen({ onError: (c) => errs.push(c), onEnd: () => {} });
assert.deepEqual(errs, ["unsupported"]);

console.log("stt.js 검사 통과 (중간·최종 결과, no-speech, aborted 제외, 중복 방지, 미지원 처리)");
