// 마이크 소리를 16kHz PCM 조각으로 바꿔 메인 스레드로 넘기는 AudioWorklet.
//
// 담당: FE1
// 같이 보는 파일: live_test.js (이 조각을 WebSocket으로 보냄), tools/live_relay_spike.py (받는 쪽)
//
// 왜 AudioWorklet인가:
//   기존 audio.js는 녹음이 끝난 뒤 한 번에 WAV로 바꾼다. Live API는 말하는 동안 계속 보내야 하므로
//   소리가 들어오는 즉시 조각으로 넘겨줄 곳이 필요하다. ScriptProcessorNode는 폐기 예정이라 쓰지 않는다.
//
// 왜 여기서 16kHz로 줄이는가:
//   Live API 입력은 16kHz·16bit·모노 PCM이다(공식 문서). 아이폰 마이크는 보통 48kHz로 들어오므로
//   비율만큼 골라내 16kHz로 만든다. 선형 보간 없이 가장 가까운 샘플을 고르는 가장 단순한 방법을 쓴다.
//   음성 인식에는 충분하다(audio.js도 같은 이유로 16kHz를 쓴다).

const TARGET_RATE = 16000;
// 한 번에 보낼 샘플 수. 너무 작으면 WebSocket 메시지가 많아지고, 너무 크면 반응이 늦다.
// 16000 × 0.1초 = 1600 샘플 = 100ms. tools/fake_browser_live.py도 100ms씩 보낸다.
const CHUNK_SAMPLES = 1600;

class MicDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(CHUNK_SAMPLES);
    this.filled = 0;
    this.position = 0; // 원본 샘플 위치(소수). 여기서 TARGET_RATE 간격으로 골라낸다.
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true; // 마이크가 아직 준비되지 않음. 노드는 계속 살려 둔다.

    // sampleRate는 AudioWorklet이 주는 전역값(이 컨텍스트의 실제 샘플레이트, 보통 48000).
    const step = sampleRate / TARGET_RATE;

    while (this.position < channel.length) {
      const sample = channel[Math.floor(this.position)];
      // -1~1 소수를 16비트 정수로. 범위를 넘는 값은 잘라낸다(audio.js의 toWav16k와 같은 방식).
      this.buffer[this.filled++] = Math.max(-1, Math.min(1, sample)) * 0x7fff;
      this.position += step;
      if (this.filled === CHUNK_SAMPLES) {
        // 복사해서 보낸다(transfer하면 this.buffer를 다시 쓸 수 없다).
        this.port.postMessage(this.buffer.slice());
        this.filled = 0;
      }
    }
    // 다음 호출로 남은 소수점 위치를 넘긴다. 이렇게 하지 않으면 조각 경계에서 소리가 튄다.
    this.position -= channel.length;
    return true;
  }
}

registerProcessor("mic-downsampler", MicDownsampler);
