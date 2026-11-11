// 서버가 보내는 24kHz PCM 조각을 끊김 없이 이어 재생한다.
//
// 담당: FE1
// 같이 보는 파일: live_test.js (조각을 넘겨줌), tools/live_relay_spike.py (보내는 쪽)
//
// 왜 따로 필요한가:
//   기존 audio.js의 speak()는 브라우저 TTS로 '문장'을 읽는다. Live는 완성된 음성 파일이 아니라
//   생 PCM 조각이 계속 도착한다. 조각마다 play()를 하면 사이가 끊기므로, 다음 조각을 앞 조각이
//   끝나는 시각에 맞춰 미리 예약해 둔다.
//
// 아이폰 Safari 주의:
//   - AudioContext는 사용자가 버튼을 누른 흐름 안에서 만들고 resume해야 한다(audio.js와 같은 제약).
//   - AudioContext에 sampleRate 24000을 요구하지 않는다. Safari 버전에 따라 무시되거나 실패한다.
//     대신 버퍼를 24000Hz로 만들어 넣고 브라우저가 알아서 변환하게 한다. 이게 더 안전하다.

const INPUT_RATE = 24000; // Live API 출력은 항상 24kHz (공식 문서, 실제 mime으로도 확인)

export function createPlayer() {
  let ctx = null;
  let nextStartTime = 0; // 다음 조각을 시작할 시각(ctx.currentTime 기준)
  let playing = 0; // 재생 중이거나 예약된 조각 수
  const sources = new Set();

  return {
    /** 사용자 조작 안에서 부른다. 여기서 AudioContext를 만든다. */
    async start() {
      if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") await ctx.resume();
      nextStartTime = 0;
      return { sampleRate: ctx.sampleRate, state: ctx.state };
    },

    /** 16비트 PCM 조각(ArrayBuffer)을 재생 줄에 세운다. */
    push(arrayBuffer) {
      if (!ctx) return;
      const pcm = new Int16Array(arrayBuffer);
      if (!pcm.length) return;

      const buffer = ctx.createBuffer(1, pcm.length, INPUT_RATE);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000; // 정수 → -1~1 소수

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);

      // 앞 조각이 끝나는 시각에 붙여 예약한다. 이미 지난 시각이면 지금 시작한다.
      // 0.05초 여유는 조각이 늦게 도착했을 때 소리가 겹치거나 튀는 것을 줄이기 위함이다.
      const now = ctx.currentTime;
      const startAt = Math.max(now + 0.05, nextStartTime);
      source.start(startAt);
      nextStartTime = startAt + buffer.duration;

      playing += 1;
      sources.add(source);
      source.onended = () => { playing -= 1; sources.delete(source); };
    },

    /** 재생을 즉시 멈춘다(관람객이 말을 끊을 때). */
    stop() {
      for (const source of sources) {
        try { source.stop(); } catch { /* 이미 끝난 조각 */ }
      }
      sources.clear();
      playing = 0;
      nextStartTime = ctx ? ctx.currentTime : 0;
    },

    /** 지금 재생 중이거나 예약된 조각 수. 화면 표시용. */
    get queued() { return playing; },
    get sampleRate() { return ctx ? ctx.sampleRate : null; },
  };
}
