# 서버 API 약속

폰 웹앱(`static/api.js`)·글라스 앱과 서버(`server/app.py`)가 주고받는 형식입니다. 이 문서가 기준이며, **바꿀 때는 이 문서를 먼저 고치고 BE1과 FE1이 함께 리뷰**합니다. 한쪽만 바꾸면 다른 쪽이 고장 납니다.

- 담당: BE1(서버), FE1(웹앱). 글라스 앱(FE2)도 이 형식을 따릅니다.
- 기준일: 2026-11-03 (v0 코드 기준)
- 정상 응답은 JSON입니다. 서버가 미리 정한 오류는 HTTP 상태 코드와 `{"detail": "설명"}`으로 오고, 예상하지 못한 오류(예: Gemini 호출 실패)는 500과 `Internal Server Error` 글자로 옵니다.

## POST `/api/session` — 관람 시작

보내는 값: 없음

받는 값:

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `session_id` | 문자열 | 이후 요청에 그대로 넣는 관람 ID |
| `reply` | 문자열 | 도슨트의 첫 인사(영어). 웹앱은 이 문장을 읽어 줍니다 |

## POST `/api/turn` — 대화 한 번

보내는 값: `multipart/form-data`(파일과 글을 함께 보내는 형식)

| 필드 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- |
| `session_id` | 예 | 문자열 | `/api/session`에서 받은 값 |
| `audio` | `text`와 둘 중 하나 | 파일, 16kHz 모노 WAV | 관람객이 말한 녹음 |
| `text` | `audio`와 둘 중 하나 | 문자열 | 글로 입력한 질문 |
| `image` | 아니요 | 파일, JPEG | 말을 끝낸 순간의 카메라 사진 한 장. 웹앱은 가로 최대 768px로 줄여 보냅니다 |

받는 값:

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `transcript` | 문자열 | 관람객의 말을 받아쓴 영어 문장 |
| `reply` | 문자열 | 이어폰으로 읽어 줄 도슨트의 답 |
| `artwork_id` | 문자열 | 인식한 작품 ID(`data/artworks.csv`). 모르면 `"unknown"` |
| `artwork_title` | 문자열 | 인식한 작품의 영문 제목. 모르면 `""` |
| `comparison_id` | 문자열 | 답에 사용한 비교쌍 ID(`data/comparisons.csv`). 안 썼으면 `""` |
| `profile` | 객체 | `{"country": "", "familiar_art": [], "depth": ""}` 지금까지 알게 된 관람객 정보 |
| `latency_ms` | 숫자 | 서버 안에서 Gemini 답을 받는 데 걸린 시간(밀리초). 전송 시간은 포함하지 않습니다 |

오류:

| 상태 코드 | 의미 | 할 일 |
| --- | --- | --- |
| 404 | 세션이 없음 | 서버를 다시 켜면 세션이 모두 사라집니다. Start부터 다시 |
| 400 | `audio`와 `text`가 둘 다 비었음 | 녹음이 비었는지 확인 |
| 500 | `{"detail": ...}`이면 서버 설정 문제(예: `.env`에 `GEMINI_MODEL` 없음), `Internal Server Error`면 Gemini 호출 실패 등 예상하지 못한 오류 | 서버 터미널의 오류 메시지 확인 |

## POST `/api/session/{session_id}/end` — 관람 끝

보내는 값: 없음. 받는 값: `{"ok": true}`. 그 세션의 기억을 서버에서 지웁니다. 지금 웹앱은 아직 이 주소를 부르지 않습니다.

## POST `/api/ask` — 텍스트 질문·답변 (BE1, 11/11 추가)

FE1이 브라우저 음성 인식으로 받아쓴 질문을 텍스트로 보내는 주소입니다. 세션 없이 작품 한 점 기준으로 답합니다. 코드: `server/ask.py`.

보내는 값: JSON (`Content-Type: application/json`)

| 필드 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- |
| `artwork_id` | 예 | 문자열 | `data/artworks.csv`의 작품 ID (예: `KHD_SSIREUM`) |
| `question` | 예 | 문자열 | 관람객의 질문(영어) |

예: `{"artwork_id": "KHD_SSIREUM", "question": "Who painted this?"}`

받는 값:

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `answer` | 문자열 | 화면에 표시하고 읽어 줄 답변. **status와 상관없이 항상 들어 있음** |
| `artwork_id` | 문자열 | 보낸 작품 ID 그대로 |
| `artwork_title` | 문자열 | 작품 영문 제목. 모르는 작품이면 `""` |
| `status` | 문자열 | `ok` 정상 / `mock` 임시 답변 / `no_artwork` 자료 없는 작품 / `error` 답변 생성 실패 |
| `source_url` | 문자열 | 근거 자료 출처(e뮤지엄 페이지). 없으면 `""` |
| `latency_ms` | 숫자 | 서버 안에서 답변을 만드는 데 걸린 시간(밀리초) |
| `model` | 문자열 | 실제로 답한 Gemini 모델. 임시 답변·실패면 `""` |

모델 예비 순서: `GEMINI_MODEL`이 과부하(503)·사용 불가·12초 초과면 `ASK_FALLBACK_MODELS`(기본 `gemini-flash-latest,gemini-3.5-flash,gemini-3.1-flash-lite`) 순서로 다음 모델을 씁니다.

오류: 400 `question`이 비었음. 자료 없는 작품과 Gemini 실패는 오류 코드 대신 `status`와 안내 문장(`answer`)으로 돌려줍니다.

임시 답변 모드: `.env`에 `ASK_MOCK=1`을 넣고 서버를 다시 켜면 Gemini 없이 `status: "mock"` 답변을 돌려줍니다.

## WS `/ws/live` — 실시간 음성 (Gemini Live API, 11/17 추가)

담당: 중계는 FE1(`server/live.py`), 지시문은 BE1(`server/live_context.py`). 경로는 11/17에 BE1과 합의했습니다.

`tools/live_relay_spike.py`는 운영 서버를 켜지 않고 중계만 띄우는 시험 서버이고, 같은 코드를 씁니다.

AGENTS.md가 클라이언트 코드에 API 키를 넣는 것을 금지하므로 폰이 Gemini Live에 직접 붙을 수 없고, 서버가 가운데서 음성을 중계합니다. 연결은 WebSocket 하나이고, 텍스트 메시지(JSON)와 바이너리 메시지(생 PCM)를 섞어서 주고받습니다.

보내는 값 (폰 → 서버):

| 순서 | 보내는 것 | 형식 |
| --- | --- | --- |
| 연결 직후 1회 | 어느 작품인지, 관람객 프로필, 이어 쓸 관람 세션 | 텍스트 `{"artwork_id": "KHD_SSIREUM", "profile": {"country": "France", "age_group": "adult", "language": "en"}, "session_id": "..."}` |
| 버튼 누름 | 말 시작 | 텍스트 `{"type": "speech_start"}` |
| 누르고 있는 동안 | 마이크 소리 | 바이너리, 16kHz 모노 PCM16 |
| 버튼 뗌 | 말 끝 | 텍스트 `{"type": "speech_end"}` |

받는 값 (서버 → 폰):

| 받는 것 | 형식 | 폰이 할 일 |
| --- | --- | --- |
| 준비됨 | `{"type": "ready", "model": "...", "artwork_title": "...", "session_id": "..."}` | 버튼 활성화. `session_id`를 관람 요약에 씁니다 |
| 받아쓴 질문 | `{"type": "heard", "text": "..."}` | 화면에 질문 표시 |
| 답변 음성 | 바이너리, 24kHz 모노 PCM16 | 이어 붙여 재생 |
| 답변 자막 | `{"type": "said", "text": "..."}` | 화면에 답 표시 |
| 턴 끝 | `{"type": "turn_complete"}` | 버튼 다시 활성화 |
| 재연결 중 | `{"type": "reconnecting", "kept_conversation": true/false}` | "잠시만요" 안내, 버튼 잠금 |
| 다시 붙음 | `{"type": "reconnected", "kept_conversation": true/false}` | 버튼 활성화 |
| 오류 | `{"type": "error", "message": "..."}` | 안내 문구 표시 |

`profile`과 `session_id`는 없어도 됩니다. `profile`은 FE2 초기 설정값 세 필드이고(없으면 영어·성인으로 말합니다), **세션 중간에 바꾸지 않습니다**(11/17 BE1 결정). `session_id`는 `POST /api/session`에서 받은 값입니다. 보내지 않거나 서버를 다시 켜서 없어진 ID면 서버가 새로 만들어 `ready`에 담아 돌려줍니다.

`kept_conversation`이 거짓이면 앞 대화가 이어지지 않으므로 폰은 안내 문구를 바꿉니다.

형식에 영향을 주는 약속:

- **자동 음성 감지(VAD)를 끄고** `activity_start`·`activity_end`로 말의 경계를 Gemini에 알립니다. 버튼을 누르는 동안만 소리를 보내므로 모델에 침묵이 전달되지 않아 말의 끝을 알 수 없습니다. 섞어 쓰면 첫 턴만 동작합니다.
- **말의 앞뒤에 300ms 무음**을 넣습니다. 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘립니다(11/11 측정에서 완전 일치 10/25 → 25/25. 실제 아이폰 중계 경로에서의 재확인은 아직입니다).

구현 내부 사정(큐 분리, `session.receive()` 재호출, 세션 수명 처리)은 이 문서 범위가 아닙니다. [`docs/11-18_통합_인터페이스.md`](11-18_통합_인터페이스.md) 1장을 보세요.

아직 없는 것:

| 없는 것 | 지금 상태 |
| --- | --- |
| 작품 변경 | 연결 직후 `artwork_id`를 한 번 받고 고정합니다. 관람객이 다른 작품으로 옮기는 방법은 정하지 않았습니다 |
| 비교쌍 사용 기록 | 턴이 끝나면 `session.record_turn`으로 본 작품과 대화를 남기지만, `comparison_id`는 빈 값입니다. Live는 음성으로 답해서 어떤 비교를 썼는지 구조화된 값으로 알 수 없습니다(`/api/turn`은 받습니다). 그래서 요약 화면의 **비교 수는 Live 경로에서 0**입니다. 함수 호출로 받는 방법을 12/1 범위로 둡니다 |
| 에코 처리 | 마이크가 답변 음성을 되받는 문제를 다루지 않습니다(이어폰 사용 전제) |
| 여러 관람객 동시 접속 | 단일 세션입니다. 인증도 없습니다(11/13 결정, 12/1 범위) |
| 10분 넘는 연결 | 세션 수명 처리는 모의 시험까지만 확인했고 실기기 확인은 아직입니다 |

## 바꿀 때 확인할 곳

| 바꾸는 것 | 함께 고칠 파일 |
| --- | --- |
| 보내는 필드 | `server/app.py`의 `turn()`, `static/api.js`의 `postTurn()`, 글라스 앱 |
| 받는 필드 | `server/app.py`의 응답, `server/gemini_client.py`의 `DocentReply`, `static/app.js`의 `sendTurn()` |
| 실시간 음성(Gemini Live API) 주고받는 형식 | 위 [WS `/ws/live`](#ws-wslive--실시간-음성-gemini-live-api-1117-추가) 절, `server/live.py`, `static/live_test.js`, `static/live_mic_worklet.js`, `static/live_player.js` (전환은 11/11 회의에서 확정) |
