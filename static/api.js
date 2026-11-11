// 서버와 주고받는 부분만 모은 파일.
//
// 담당: FE1 (형식을 바꿀 때는 BE1과 합의)
// 같이 보는 파일: docs/api.md (요청·응답 약속), server/app.py (서버 쪽 구현)
//
// 글라스 앱(FE2)도 같은 서버를 쓰므로, 이 파일이 보내는 형식이 글라스 앱이 따라야 할 형식이다.

import { API_BASE } from "./config.js";

// 보낼 주소를 만든다. config.js의 API_BASE가 ""이면 웹앱을 내려준 그 서버로 보낸다.
const url = (path) => `${API_BASE}${path}`;

// 관람을 시작한다. 돌려받는 값: { session_id, reply(첫 인사) }
export async function startSession() {
  const res = await fetch(url("/api/session"), { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// 대화 한 번을 보낸다. audio(WAV)와 text 중 하나 이상, frame(JPEG)은 있으면 함께 보낸다.
// 돌려받는 값: { transcript, reply, artwork_id, artwork_title, comparison_id, profile, latency_ms }
export async function postTurn({ sessionId, audio, text, frame }) {
  const form = new FormData(); // 파일(음성·사진)과 글을 한 번에 보내는 형식(multipart/form-data)
  form.append("session_id", sessionId);
  if (text) form.append("text", text);
  if (audio) form.append("audio", audio, "speech.wav");
  if (frame) form.append("image", frame, "frame.jpg");
  const res = await fetch(url("/api/turn"), { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// 작품 ID와 질문 텍스트만 보내 답변을 받는다(텍스트 전용, 음성·사진 없음). 세션을 쓰지 않는다.
// 돌려받는 값: { answer, artwork_id, artwork_title, status, source_url, latency_ms, model }
// status: "ok" 정상 / "mock" 임시 답변 / "no_artwork" 자료 없는 작품 / "error" 답변 생성 실패.
// 주의: no_artwork와 error도 HTTP 200이고 answer에 읽어 줄 문장이 들어 있다. 400은 질문이 빈 경우뿐이다.
export async function postAsk({ artworkId, question }) {
  const res = await fetch(url("/api/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artwork_id: artworkId, question }),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
