// 브라우저 음성 인식(STT): 관람객의 말을 질문 텍스트로 바꾼다.
//
// 담당: FE1
// 같이 보는 파일: app.js (이 함수들을 부름), audio.js (답변 음성 출력), docs/FE1_음성_비교.md
//
// 이것은 서버로 녹음을 보내는 기존 흐름(/api/turn)과 다른 방법이다. 녹음 파일을 만들지 않고
// 브라우저가 바로 글자를 준다. 대신 두 가지를 알고 써야 한다.
//
//   1) 브라우저가 소리를 자기 회사 서버로 보내 글자로 바꾼다(아이폰은 Apple, 크롬은 Google).
//      우리 서버를 거치지 않지만 기기 밖으로 나가는 것은 맞다. 오프라인이 아니다.
//      AGENTS.md: 음성은 처리에만 쓰고 저장하지 않는다 — 이 파일도 녹음을 남기지 않는다.
//   2) 모든 브라우저에 있지 않다. 없으면 isSupported()가 false이고, 그때는 글로 입력받는다.
//
// 아이폰 Safari는 사용자가 버튼을 누른 흐름에서만 마이크를 허용한다. start()를 await 뒤에서
// 부르지 않는다(audio.js의 initAudio와 같은 이유).

// 브라우저마다 이름이 다르다. Safari와 Chrome은 webkit 접두사를 쓴다.
const Recognition = typeof window === "undefined"
  ? null
  : window.SpeechRecognition || window.webkitSpeechRecognition;

export function isSupported() {
  return Boolean(Recognition);
}

let current = null; // 지금 듣고 있는 인식기. 두 개가 동시에 돌지 않게 하나만 둔다.

/** 듣기를 시작한다. 콜백:
 *    onPartial(text)  말하는 중간 결과. 화면에 흐리게 보여 주면 반응이 빠르게 느껴진다.
 *    onFinal(text)    최종 질문 텍스트. 이것을 서버로 보낸다.
 *    onError(code)    "not-allowed" 마이크 거부 / "no-speech" 말이 없음 / "network" 등
 *    onEnd()          듣기가 끝났을 때(성공·실패 모두). 버튼 상태를 되돌리는 데 쓴다.
 *  돌려주는 값: 듣기를 멈추는 함수.
 */
export function listen({ onPartial, onFinal, onError, onEnd, lang = "en-US" } = {}) {
  if (!Recognition) {
    onError?.("unsupported");
    onEnd?.();
    return () => {};
  }
  stopListening(); // 이전 것이 남아 있으면 멈춘다

  const recognition = new Recognition();
  current = recognition;
  recognition.lang = lang; // 관람객은 영어로 질문한다(docs/개발계획서.md)
  recognition.interimResults = true; // 말하는 중간 결과도 받는다
  recognition.continuous = false; // 한 번 말하면 끝. 계속 듣지 않는다(마이크를 오래 열어 두지 않기 위함)
  recognition.maxAlternatives = 1;

  let finalText = "";
  let reportedError = false; // 오류를 이미 알렸으면 onend에서 no-speech로 덮어쓰지 않는다

  recognition.onresult = (event) => {
    let partial = "";
    for (const result of event.results) {
      if (result.isFinal) finalText += result[0].transcript;
      else partial += result[0].transcript;
    }
    if (partial) onPartial?.(partial);
  };

  recognition.onerror = (event) => {
    if (current !== recognition) return; // 이미 다른 인식기로 바뀌었으면 무시
    // "aborted"는 우리가 일부러 멈춘 것이므로 오류로 보지 않는다(audio.js의 취소 처리와 같은 이유).
    if (event.error === "aborted") return;
    reportedError = true;
    onError?.(event.error);
  };

  recognition.onend = () => {
    if (current !== recognition) return;
    current = null;
    const text = finalText.trim();
    // 규격상 error 뒤에 end가 따라온다. 이때 no-speech를 또 알리면 마이크 거부 같은
    // 진짜 원인이 "못 알아들었다"로 덮여 관람객이 엉뚱한 안내를 보게 된다.
    if (text) onFinal?.(text);
    else if (!reportedError) onError?.("no-speech"); // 말이 없었거나 알아듣지 못했다
    onEnd?.();
  };

  try {
    recognition.start();
  } catch (error) {
    current = null;
    onError?.(error.message);
    onEnd?.();
  }
  return () => stopListening();
}

/** 듣기를 멈춘다. 지금까지 알아들은 내용은 onend에서 최종 결과로 올라온다. */
export function stopListening() {
  if (!current) return;
  const recognition = current;
  try {
    recognition.stop();
  } catch {
    current = null;
  }
}
