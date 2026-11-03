// 소리와 관련된 부분만 모은 파일: 녹음 형식 변환(WAV)과 영어 음성 출력.
//
// 담당: FE1 (글라스 앱을 만드는 FE2가 녹음·재생 방식을 참고)
// 같이 보는 파일: app.js (이 함수들을 부름), api.js (변환한 WAV를 서버로 보냄)

let audioCtx = null;

// 소리 처리 장치를 준비한다. iOS는 사용자가 화면을 탭한 직후에만 소리 기능을 열어 주므로,
// 반드시 Start 버튼 클릭 안에서 불러야 한다.
export function initAudio() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  speak(""); // 빈 문장을 한 번 읽어 음성 출력 권한을 미리 열어 둔다(iOS).
}

// 영어 문장을 브라우저 내장 음성으로 읽는다. 읽던 문장이 있으면 끊고 새로 읽는다.
export function speak(text) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  const voice = speechSynthesis.getVoices().find((v) => v.lang === "en-US");
  if (voice) u.voice = voice;
  speechSynthesis.speak(u);
}

export function stopSpeaking() {
  speechSynthesis.cancel();
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
