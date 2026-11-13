// live_mic_worklet.js의 16kHz 변환을 브라우저 없이 확인한다.
//
// 담당: FE1
// 실행: node tests/test_live_mic.mjs
// 확인하는 것: 마이크 샘플레이트가 무엇이든 16kHz로 나오는지, 조각 경계에서 샘플이 밀리거나
//              겹치지 않는지(길게 돌려도 누적 오차가 생기지 않는지), 조각 크기와 값 변환이 맞는지.
//
// 이 부분이 틀리면 Live API가 말을 잘못 알아듣는다. 아이폰에서 확인하기 전에 계산부터 맞춰 둔다.
import assert from "node:assert";

// AudioWorklet 환경 흉내: 전역 sampleRate와 등록 함수, 베이스 클래스를 준다.
let Processor = null;
globalThis.registerProcessor = (name, cls) => { Processor = { name, cls }; };
globalThis.AudioWorkletProcessor = class { constructor() { this.port = { postMessage: () => {} }; } };

async function loadWithRate(rate) {
  globalThis.sampleRate = rate;
  // 캐시를 피해 매번 새로 읽는다(모듈 평가 시점에 sampleRate를 읽지는 않지만, 인스턴스를 깨끗이 쓰기 위함)
  await import(`${new URL("../static/live_mic_worklet.js", import.meta.url)}?rate=${rate}`);
  const node = new Processor.cls();
  const chunks = [];
  node.port = { postMessage: (data) => chunks.push(data) };
  return { node, chunks };
}

const BLOCK = 128; // 브라우저가 한 번에 주는 샘플 수
const CHUNK_SAMPLES = 1600; // worklet이 한 조각에 담는 샘플 수(100ms @16kHz)

for (const rate of [48000, 44100, 16000, 32000]) {
  const { node, chunks } = await loadWithRate(rate);

  // 1초 분량을 BLOCK씩 넣는다
  const blocks = Math.floor(rate / BLOCK);
  for (let b = 0; b < blocks; b++) {
    const input = new Float32Array(BLOCK);
    for (let i = 0; i < BLOCK; i++) {
      const n = b * BLOCK + i;
      input[i] = Math.sin((2 * Math.PI * 440 * n) / rate); // 440Hz
    }
    assert.equal(node.process([[input]]), true, "노드는 계속 살아 있어야 한다");
  }

  // 넣은 입력 샘플 수에 대해 나와야 할 16kHz 샘플 수와, 실제로 만든 수(보낸 조각 + 아직 덜 찬 조각)를
  // 정확히 비교한다. 조각 경계에서 위치를 잘못 이어 가면 여기서 차이가 쌓여 잡힌다.
  const inputSamples = blocks * BLOCK;
  const expected = Math.round(inputSamples / (rate / 16000));
  const produced = chunks.length * CHUNK_SAMPLES + node.filled;
  assert.ok(
    Math.abs(produced - expected) <= 1,
    `${rate}Hz: 입력 ${inputSamples} 샘플 → ${produced} 샘플 생성. ${expected} 이어야 한다(누적 오차 의심)`
  );
  for (const chunk of chunks) {
    assert.ok(chunk instanceof Int16Array, "16비트 정수 배열이어야 한다");
    assert.equal(chunk.length, CHUNK_SAMPLES);
  }
  console.log(`  ${rate} Hz: 입력 ${inputSamples} → 16kHz ${produced} 샘플 (기대 ${expected}, 조각 ${chunks.length}개)`);
}

// 값 변환: -1~1 소수가 16비트 정수 범위로, 범위를 넘는 값은 잘린다
{
  const { node, chunks } = await loadWithRate(16000); // step 1 → 입력 그대로
  const input = new Float32Array(BLOCK).fill(0);
  input[0] = 1; input[1] = -1; input[2] = 2; input[3] = -2; input[4] = 0.5;
  for (let b = 0; b < Math.ceil(CHUNK_SAMPLES / BLOCK); b++) node.process([[b === 0 ? input : new Float32Array(BLOCK)]]);
  const first = chunks[0];
  assert.equal(first[0], 32767, "1.0 → 32767");
  assert.equal(first[1], -32767, "-1.0 → -32767");
  assert.equal(first[2], 32767, "1.0을 넘는 값은 잘린다");
  assert.equal(first[3], -32767, "-1.0 미만도 잘린다");
  assert.equal(first[4], Math.trunc(0.5 * 0x7fff), "0.5 → 16383 (Int16Array는 소수를 버린다)");
}

// 마이크가 아직 없을 때(빈 입력) 죽지 않는다
{
  const { node } = await loadWithRate(48000);
  assert.equal(node.process([[]]), true);
  assert.equal(node.process([]), true);
}

console.log("live_mic_worklet.js 검사 통과 (여러 샘플레이트에서 16kHz 유지, 조각 경계 누적 오차 없음, 값 변환·빈 입력)");
