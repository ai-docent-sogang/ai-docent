// live_player.js의 24kHz PCM 이어 재생을 브라우저 없이 확인한다.
//
// 담당: FE1
// 실행: node tests/test_live_player.mjs
// 확인하는 것: 조각이 앞 조각 끝에 정확히 붙어 예약되는지(겹치거나 벌어지면 소리가 끊긴다),
//              늦게 도착한 조각도 겹치지 않는지, stop()이 예약까지 취소하는지, 값 변환이 맞는지.
import assert from "node:assert";

// AudioContext 흉내. 예약된 시작 시각과 길이를 기록해 두고 검사한다.
const started = [];
let now = 0;

class FakeSource {
  constructor() { this.buffer = null; this.stopped = false; this.onended = null; }
  connect() { return this; }
  start(at) { started.push({ at, duration: this.buffer.duration }); this.startedAt = at; }
  stop() {
    if (this.startedAt === undefined) throw new Error("not started");
    this.stopped = true;
  }
}

class FakeContext {
  constructor() { this.sampleRate = 48000; this.state = "running"; this.destination = {}; }
  get currentTime() { return now; }
  async resume() { this.state = "running"; }
  createBuffer(channels, length, rate) {
    const data = new Float32Array(length);
    return { length, sampleRate: rate, duration: length / rate, getChannelData: () => data };
  }
  createBufferSource() { return new FakeSource(); }
}

globalThis.window = { AudioContext: FakeContext };

const { createPlayer } = await import(new URL("../static/live_player.js", import.meta.url));
const player = createPlayer();

const info = await player.start();
assert.equal(info.sampleRate, 48000, "브라우저가 주는 실제 샘플레이트를 그대로 알려야 한다");

// 24kHz에서 2400 샘플 = 0.1초짜리 조각 3개를 연달아 넣는다
const chunk = () => new Int16Array(2400).buffer;
player.push(chunk());
player.push(chunk());
player.push(chunk());

assert.equal(started.length, 3, "조각마다 하나씩 예약되어야 한다");
for (const s of started) assert.ok(Math.abs(s.duration - 0.1) < 1e-9, `길이가 0.1초여야 한다: ${s.duration}`);

// 두 번째·세 번째가 앞 조각이 끝나는 시각에 정확히 붙어야 한다
assert.ok(Math.abs(started[1].at - (started[0].at + 0.1)) < 1e-9,
  `두 번째 조각이 ${started[1].at}에 예약됨. ${started[0].at + 0.1}이어야 한다(틈이 생기면 소리가 끊긴다)`);
assert.ok(Math.abs(started[2].at - (started[1].at + 0.1)) < 1e-9, "세 번째 조각도 이어 붙어야 한다");
assert.equal(player.queued, 3);

// 늦게 도착한 경우: 예약이 모두 끝난 뒤에 넣으면 지금 시각 기준으로 시작한다(과거 시각에 예약하지 않는다)
now = started[2].at + 5;
player.push(chunk());
assert.ok(started[3].at >= now, `지난 시각에 예약하면 안 된다: ${started[3].at} < ${now}`);

// stop(): 예약된 것까지 멈추고 줄을 비운다
player.stop();
assert.equal(player.queued, 0, "멈추면 대기 수가 0이어야 한다");

// 멈춘 뒤에도 새 조각을 받을 수 있다
const before = started.length;
player.push(chunk());
assert.equal(started.length, before + 1, "멈춘 뒤에도 다시 재생할 수 있어야 한다");

// 빈 조각은 무시한다
const count = started.length;
player.push(new Int16Array(0).buffer);
assert.equal(started.length, count, "빈 조각은 예약하지 않는다");

// 값 변환: 16비트 정수 → -1~1 소수
{
  const pcm = new Int16Array([32767, -32768, 0, 16384]);
  const fresh = createPlayer();
  await fresh.start();
  let channel = null;
  const origCreate = FakeContext.prototype.createBuffer;
  FakeContext.prototype.createBuffer = function (c, length, rate) {
    const buffer = origCreate.call(this, c, length, rate);
    channel = buffer.getChannelData(0);
    return buffer;
  };
  fresh.push(pcm.buffer);
  FakeContext.prototype.createBuffer = origCreate;
  assert.ok(Math.abs(channel[0] - 32767 / 32768) < 1e-6, "최대값");
  assert.equal(channel[1], -1, "최소값은 -1");
  assert.equal(channel[2], 0);
  assert.equal(channel[3], 0.5, "16384 → 0.5");
}

console.log("live_player.js 검사 통과 (조각 이어 붙이기, 늦은 도착, stop 후 재사용, 빈 조각, 값 변환)");
