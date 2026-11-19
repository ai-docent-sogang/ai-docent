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

## 운영 API (FE1, 11/19 추가) — 관람객 화면이 아닙니다

운영자가 보는 주소입니다. 코드: `server/admin.py`. 집계 수식은 `server/visit_stats.py`, 작품 켜기/끄기 상태는 `server/on_view.py`에 있습니다.

**인증이 없습니다.** 아래 `POST`는 상태를 바꾸므로 주소를 아는 사람이 작품을 끌 수 있습니다. 공개 주소(cloudflared 등)로 서버를 열 때는 운영 페이지를 쓰지 않습니다.

### GET `/api/admin/stats` — 관람 기록 집계

보내는 값(쿼리):

| 이름 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- |
| `from_day` | 아니오 | `YYYY-MM-DD` | 비우면 오늘 |
| `to_day` | 아니오 | `YYYY-MM-DD` | 비우면 오늘 |
| `source_kind` | 아니오 | 문자열 | 기본 `team_rehearsal`. **한 종류만** 받습니다. 모의와 실측을 합산하지 않기로 한 11/16 결정 때문입니다 |

받는 값(주요 칸):

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `range` | 객체 | `from`·`to`·읽은 파일 목록·귀속 규칙 |
| `visits` | 객체 | 관람 수, 종료된 수, 종료 기록 없는 수, 관람 길이 중앙값 |
| `artworks` | 목록 | 작품별 인식 보고 수, 인식 구간, 재방문, 질문 수, 원라벨 10개, 덩이 3개, 결과 4개, 비교 수, 토큰, 제목, 켜짐·꺼짐 |
| `artworks_without_records` | 목록 | 기간 안에 기록이 없는 작품 ID. 아무도 묻지 않은 작품도 콘텐츠 공백의 신호입니다 |
| `totals` | 객체 | 전체 질문 수와 라벨·덩이·결과 합계, 작품이 비어 있던 질문 수, 보고가 없던 질문 수, 인식 실패 수 |
| `transitions`, `sequences` | 목록 | 작품 간 전환과 관람 순서 |
| `first_audio_ms` | 객체 | 중앙값·p90·재지 못한 수. **관람객이 기다린 시간보다 약 1초 작습니다** |
| `quality`, `end_reasons` | 객체 | 끼어들기·재연결 등과 종료 이유 |
| `warnings` | 목록 | 집계에서 뺀 기록과 이유 |

**비율을 서버가 계산하지 않습니다.** 분자와 분모를 함께 돌려주고 `a/b (p%)` 표기와 분모 0일 때의 `N/A`는 화면이 맡습니다.

주의 둘. `visit`은 사람이 아니라 **폰 연결 1회**입니다(재연결하면 관람이 둘로 세어집니다). 작품별 "인식 구간"은 특정 작품 인식부터 다른 작품 인식까지이고 **체류 시간이 아닙니다**.

오류: 400 날짜 형식이 틀림 / 기간이 거꾸로 / 모르는 `source_kind`.

### GET `/api/admin/artworks` — 작품 목록과 켜짐·꺼짐

받는 값: `artworks`(각 항목 `artwork_id`·`title_en`·`on_view`), `off`(꺼진 작품 ID 목록), `note`.

### POST `/api/admin/artworks/{artwork_id}/on_view` — 작품 켜고 끄기

보내는 값: `{"on_view": true}` 또는 `{"on_view": false}`. 받는 값: `changed`(실제로 바뀌었는지)와 위 목록을 함께 돌려줍니다. 오류: 404 모르는 `artwork_id`.

끈 작품은 Live의 도구 값 목록과 전시작 목록, 함수 결과에서 함께 빠지고 그 작품의 비교쌍도 빠집니다. **상태는 메모리에만 있습니다.** 서버를 다시 켜면 `.env`의 `LIVE_OFF_ARTWORKS`만 남고 나머지는 모두 켜집니다. `data/artworks.csv`의 `on_view_status`(FE3가 적는 현장 확인 상태)와는 다른 사실이며 서로 읽지 않습니다. `/api/turn`과 `/api/ask`는 거르지 않습니다. 호출자가 작품 ID를 직접 주는 경로이기 때문입니다.

## 바꿀 때 확인할 곳

| 바꾸는 것 | 함께 고칠 파일 |
| --- | --- |
| 보내는 필드 | `server/app.py`의 `turn()`, `static/api.js`의 `postTurn()`, 글라스 앱 |
| 받는 필드 | `server/app.py`의 응답, `server/gemini_client.py`의 `DocentReply`, `static/app.js`의 `sendTurn()` |
| 운영 API의 집계 칸 | `server/visit_stats.py`, `server/admin.py`, `static/admin.js`, 이 문서 |
| 실시간 음성(Gemini Live API)으로 전환 | 이 문서 전체를 새로 씁니다(역할 가이드 3장의 방식 비교 실험 결과에 따라 결정) |
