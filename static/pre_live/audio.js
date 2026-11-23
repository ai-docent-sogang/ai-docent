// 소리와 관련된 부분만 모은 파일: 녹음 형식 변환(WAV)과 영어 음성 출력.
//
// 담당: FE1 (글라스 앱을 만드는 FE2가 녹음·재생 방식을 참고)
// 같이 보는 파일: app.js (이 함수들을 부름), api.js (변환한 WAV를 서버로 보냄)

let audioCtx = null;

// Start의 첫 await 전에 호출한다. 빈 발화가 이후 재생을 허용한다고 가정하지 않는다.
export function initAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") return audioCtx.resume();
  return Promise.resolve();
}

let currentUtterance = null;

export function speak(text, { onStart, onEnd, onError } = {}) {
  stopSpeaking();
  if (!text.trim()) return;
  if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
    onError?.("unsupported");
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  currentUtterance = u;
  u.lang = "en-US";
  const voice = speechSynthesis.getVoices().find((v) => v.lang === "en-US");
  if (voice) u.voice = voice;
  u.onstart = () => { if (currentUtterance === u) onStart?.(); };
  u.onend = () => {
    if (currentUtterance !== u) return;
    currentUtterance = null;
    onEnd?.();
  };
  u.onerror = (event) => {
    if (currentUtterance !== u) return;
    currentUtterance = null;
    onError?.(event.error);
  };
  try {
    speechSynthesis.speak(u);
  } catch (error) {
    currentUtterance = null;
    onError?.(error.message);
  }
}

export function stopSpeaking() {
  currentUtterance = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

// 녹음 파일을 16kHz 모노 WAV로 바꾼다.
// 이유: 브라우저마다 녹음 형식이 다르다(iOS는 mp4/AAC, Chrome은 webm/Opus). 서버와 Gemini가
// 한 가지 형식만 받으면 되도록 가장 단순한 WAV로 통일한다. 음성 인식에는 16kHz 한 채널이면 충분하다.
export async function toWav16k(blob) {
  // 1) 녹음 파일을 소리 샘플(-1~1 사이 숫자 배열)로 풀고, 16kHz 한 채널로 다시 맞춘다.
  const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
  const rate = 16000;
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  // 2) WAV 파일 = 44바이트 머리말(형식 정보) + 소리 데이터(샘플 하나당 2바이트).
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const writeStr = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  writeStr(0, "RIFF"); // 파일 종류 표시
  view.setUint32(4, 36 + samples.length * 2, true); // 이 위치 뒤의 파일 크기
  writeStr(8, "WAVE");
  writeStr(12, "fmt "); // 형식 정보 시작
  view.setUint32(16, 16, true); // 형식 정보 길이(16바이트)
  view.setUint16(20, 1, true); // 압축 없음(PCM)
  view.setUint16(22, 1, true); // 채널 1개(모노)
  view.setUint32(24, rate, true); // 초당 샘플 수(16000)
  view.setUint32(28, rate * 2, true); // 초당 바이트 수 = 샘플 수 × 2바이트
  view.setUint16(32, 2, true); // 샘플 하나의 바이트 수
  view.setUint16(34, 16, true); // 샘플 하나의 비트 수(16비트)
  writeStr(36, "data"); // 소리 데이터 시작
  view.setUint32(40, samples.length * 2, true); // 소리 데이터 크기

  // 3) -1~1 사이 소수를 16비트 정수(-32767~32767)로 바꿔 채운다. 범위를 넘는 값은 잘라낸다.
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}
