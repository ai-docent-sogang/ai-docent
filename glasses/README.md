# 글라스 연동 (FE2)

담당: FE2. 역할과 주차별 할 일은 [역할 가이드 6장](../docs/역할_가이드.md)을 봅니다.

이 폴더에 둘 것:
- 상용 글라스 후보 비교표: 카메라 영상 접근 가능 여부, 필요한 개발 도구(SDK), 가격·구매 가능 여부, 아이폰 지원 여부
- 최소 대안(블루투스 이어폰·마이크 + 폰 카메라) 시험 기록
- 글라스 앱 코드

글라스 앱은 폰 웹앱과 같은 서버 API를 씁니다. 형식의 기준은 [`docs/api.md`](../docs/api.md)입니다.

**본선은 `WS /ws/live` 스트리밍입니다.** 연결 하나로 음성·사진·글이 오갑니다.

- 첫 메시지: `{"mode":"handsfree","session_id":"...","profile":{...}}`. `session_id`는 `POST /api/session`에서 받습니다.
- 글라스 → 서버: 마이크 소리(바이너리, 16kHz 모노 PCM16), 카메라 사진(`{"type":"frame","jpeg":"<base64>"}`, 3초마다), 글 질문(`{"type":"text"}`), 살아 있다는 신호(`{"type":"ping"}`).
- 서버 → 글라스: `ready`, 받아쓴 질문(`heard`), 답변 음성(바이너리, 24kHz 모노 PCM16), 답변 자막(`said`), `interrupted`, `turn_complete`, 작품 인식(`artwork`), 비교 작품(`comparison`), 재연결(`reconnecting`·`reconnected`), `error`.
- 관람을 끝낼 때 `POST /api/session/{session_id}/end`를 부릅니다.

`POST /api/turn`(사진 JPEG, 소리 16kHz WAV)은 Live 연결이 실패할 때만 쓰는 안전망입니다. 메시지 전체 표는 [`docs/api.md`](../docs/api.md)의 `/ws/live` 절을 봅니다.
