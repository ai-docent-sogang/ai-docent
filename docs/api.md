# 서버 API 약속

폰 웹앱(`static/api.js`)·글라스 앱과 서버(`server/app.py`)가 주고받는 형식입니다. 이 문서가 기준이며, **바꿀 때는 이 문서를 먼저 고치고 BE1과 FE1이 함께 리뷰**합니다. 한쪽만 바꾸면 다른 쪽이 고장 납니다.

- 담당: BE1(서버), FE1(웹앱). 글라스 앱(FE2)도 이 형식을 따릅니다.
- 기준일: 2026-11-23. `/ws/live`와 운영 API는 11/23 코드 기준이고, 나머지 `/api/*` 절은 11/03 v0 기준에 11/23 수정을 더했습니다
- 정상 응답은 JSON입니다. 서버가 미리 정한 오류는 HTTP 상태 코드와 `{"detail": "설명"}`으로 오고, 예상하지 못한 오류(예: Gemini 호출 실패)는 500과 `Internal Server Error` 글자로 옵니다.

## 지금 쓰는 API 한눈에 (2026-11-23)

| 주소 | 누가 부르나 | 언제 쓰나 |
| --- | --- | --- |
| `WS /ws/live` | 폰 웹앱(`static/live/live_conversation.js`) | **본선.** 관람 중 음성·사진·글 대화 전부 |
| `POST /api/session` | 폰 웹앱 | 관람을 시작할 때 `session_id`를 받는다 |
| `POST /api/session/{session_id}/end` | 폰 웹앱 | 관람을 끝낼 때. 서버 기억을 지우고 남은 Live 연결을 닫는다 |
| `POST /api/turn` | 폰 웹앱 | **안전망.** Live 연결이 실패하면 화면이 마이크 탭 녹음으로 돌아가 이 주소로 묻는다 |
| `GET /`, `GET /static/*` | 관람객 폰 | 웹앱 화면과 스크립트 |
| `GET /admin`, `GET /api/admin/*`, `POST /api/admin/artworks/{id}/on_view` | 운영자 | 운영 페이지, 집계, 작품 켜기/끄기 |
| `GET /live`, `GET /live/status` | 개발자 | Live 시험 페이지, 연결 상태 확인 |

`POST /api/ask`는 11/23에 폐기했습니다. 화면이 부르지 않았고, 입력원이던 브라우저 STT도 쓰지 않기로 했습니다.

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

보내는 값: 없음. 받는 값: `{"ok": true}`. 그 세션의 기억을 서버에서 지우고, 그 관람에 남은 Live 연결과 재개 정보도 지웁니다. 웹앱은 END VISIT에서 이 주소를 부릅니다.

## WebSocket `/ws/live` — Live 음성 대화 (FE1, 11/23 추가)

본선 경로입니다. 관람 중의 음성·사진·글 대화가 이 연결 하나로 오갑니다. 코드는 서버 `server/live/live.py`, 폰 `static/live/live_conversation.js`입니다. 음성과 사진은 Gemini로 넘기기만 하고 저장하지 않습니다. 인증이 없고, 한 관람(`session_id`)에는 연결을 하나만 둡니다.

모드가 둘입니다.

| 모드 | 누가 쓰나 | 특징 |
| --- | --- | --- |
| `handsfree` | 폰 웹앱 | 마이크 소리를 계속 보내고 사진을 3초마다 보냅니다. 말의 시작과 끝은 모델이 자동으로 감지하고, 작품도 모델이 사진을 보고 고릅니다 |
| `push` | `/live` 시험 페이지 | 버튼을 누르는 동안만 소리를 보냅니다. 작품은 첫 메시지로 정해집니다. 사진·글 메시지는 받지 않습니다 |

### 순서

1. `POST /api/session`으로 `session_id`를 받습니다. 요약 화면과 END VISIT가 이 값을 씁니다.
2. `/ws/live`를 열고 첫 메시지를 보냅니다.
3. 서버가 `ready`를 보냅니다. 이때부터 마이크 소리와 사진을 보냅니다.
4. 관람 중에는 아래 표대로 주고받습니다.
5. 관람을 끝낼 때 `POST /api/session/{session_id}/end`를 부릅니다. 서버가 남은 연결을 1000으로 닫습니다.

### 첫 메시지 (폰 → 서버, 텍스트 JSON, 연결 직후 한 번)

| 필드 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- |
| `mode` | handsfree면 예 | `"handsfree"` 또는 `"push"` | 없거나 다른 값이면 push로 봅니다 |
| `session_id` | 아니오 | 문자열 | `/api/session`에서 받은 값. 없거나 서버를 다시 켜서 사라졌으면 새로 만들고 `ready`에 담아 돌려줍니다 |
| `profile` | 아니오 | 객체 | `language`(`en`·`ko`·`zh`·`ja`), `region` 또는 `country`(`north-america`·`europe`·`china`·`japan` 또는 국가 이름), `age_group` 또는 `age`(`10-19`·`20-29`…`60+` 또는 `child`·`teen`·`adult`·`senior`). 연결할 때 한 번만 넣고 도중에 바꾸지 않습니다 |
| `resume` | 아니오 | `true` | 같은 관람에 이어 붙일 때. 아래 "끊기거나 바뀔 때" 참고 |
| `artwork_id` | push면 예 | 문자열 | push에서 모르는 작품이면 `{"type":"error","message":"unknown artwork"}`를 보내고 닫습니다. handsfree에서는 있으면 그 작품으로 시작하고, 없거나 꺼진 작품이면 무시합니다 |

### 폰 → 서버 (첫 메시지 이후)

| 보내는 것 | 형식 | 모드 |
| --- | --- | --- |
| 마이크 소리 | 바이너리. 16kHz 모노 PCM16. 웹앱은 100ms(1600샘플)씩 보냅니다 | 둘 다 |
| 카메라 사진 | `{"type":"frame","jpeg":"<base64 JPEG>"}`. 웹앱은 3초마다, 가로 1100px 이하, 품질 0.7로 보냅니다 | handsfree |
| 글로 묻기 | `{"type":"text","text":"..."}` | handsfree |
| 살아 있다는 신호 | `{"type":"ping"}`. 웹앱은 5초마다 보냅니다. 서버는 받기만 하고 Gemini로 넘기지 않습니다 | handsfree |
| 말 시작 · 말 끝 | `{"type":"speech_start"}`, `{"type":"speech_end"}` (버튼 누름·뗌) | push |

### 서버 → 폰

| 받는 것 | 형식 | 폰이 할 일 |
| --- | --- | --- |
| 준비됨 | `{"type":"ready","model","mode","voice","session_id"}`. 시작 작품을 알면 `artwork_title`, `resume:true`로 연 연결이면 `resumed`(앞 대화를 이었는지)가 더해집니다 | 연결 완료. `session_id`를 저장하고 마이크·사진 전송을 시작 |
| 받아쓴 질문 | `{"type":"heard","text"}` 조각 | 이어 붙여 질문으로 표시 |
| 답변 음성 | 바이너리. 24kHz 모노 PCM16 | 이어 붙여 재생 |
| 답변 자막 | `{"type":"said","text"}` 조각 | 이어 붙여 답으로 표시 |
| 끼어들기 | `{"type":"interrupted"}` | 재생 중인 소리를 바로 멈춤 |
| 턴 끝 | `{"type":"turn_complete"}`. **모델이 함수를 부른 직후에는 말 없는 `turn_complete`가 먼저 오고, 답변(`said`·음성)은 그 뒤에 옵니다.** 질문 하나에 두 번 올 수 있습니다 | 한 번 받았다고 질문이 끝났다고 보지 않음. 답변 자막이 나온 뒤의 `turn_complete`를 한 턴의 끝으로 봄 |
| 작품 인식 | `{"type":"artwork","artwork_id","artwork_title","artist"}` | 화면의 작품 표시를 바꿈. 새 칸이 더해져도 버리지 말고 그대로 넘깁니다 |
| 비교 작품 | `{"type":"comparison","comparison_id","artwork_id","source","foreign_title","foreign_artist","foreign_collection","foreign_url"}`. `source`는 `function`(모델이 함수로 보고) 또는 `transcript`(함수 없이 말한 비교를 자막에서 찾음) | 요약 화면용 비교 기록 |
| 재연결 중 | `{"type":"reconnecting"}`. `kept_conversation`(참·거짓)이 함께 오기도 합니다 | 입력을 잠그고 "잠시만요" 안내 |
| 다시 붙음 | `{"type":"reconnected","model","mode","voice","session_id","kept_conversation"}` | 잠금 해제. `kept_conversation`이 거짓이면 앞 대화가 이어지지 않았으니 안내를 바꿈 |
| 오류 | `{"type":"error","message"}` | 연결 전이면 실패, 연결 뒤면 재연결 |

모르는 `type`은 무시합니다. 서버가 먼저 새 메시지를 더해도 폰이 멈추지 않아야 합니다.

### 끊기거나 바뀔 때

- **Gemini 쪽 연결이 끊기면** 서버가 알아서 다시 붙입니다(`GoAway` 예고, 비활성 종료, 핸들 거부). 폰은 `reconnecting`에서 `reconnected`까지 입력을 잠급니다.
- **폰 연결이 끊기면** 같은 `session_id`와 `profile`에 `"resume": true`를 더해 첫 메시지를 다시 보냅니다. 서버가 저장해 둔 재개 정보와 작품으로 이어 갑니다. 저장은 연결이 끊긴 뒤 2시간입니다. 웹앱은 `session_id`를 `sessionStorage`에 두어 새로고침 뒤에도 이어 붙입니다.
- **폰이 30초 동안 아무것도 보내지 않으면** 서버가 죽은 연결로 보고 4001(`no input from the phone`)로 닫습니다. handsfree만 해당합니다. 그래서 `ping`을 보냅니다.
- **같은 `session_id`로 새 연결이 오면** 앞 연결을 4000(`replaced by a newer connection`)으로 닫습니다.
- **웹앱의 재연결 간격**은 1초에서 시작해 두 배씩 늘려 최대 15초이고, 연결을 여는 제한 시간은 12초입니다.
- **Live 연결 자체가 실패하면** 웹앱은 마이크 탭 녹음으로 돌아가 `POST /api/turn`을 씁니다.

### 서버 안에서 일어나는 일 (폰에는 안 보입니다)

- **작품 인식은 모델이 합니다.** 모델이 3초마다 오는 사진을 보고 `report_current_artwork(artwork_id)`를 부릅니다. 값은 켜져 있는 작품 ID와 `unknown`이고, 이 함수가 인식의 전부입니다. 별도의 탐지·검색 모듈을 거치지 않습니다.
- `report_comparison(comparison_id)`는 지금 작품의 검증된 비교쌍만 받습니다. 아니면 거절하고 쓸 수 있는 ID를 돌려줍니다.
- 질문마다 `lookup_facts(label, outcome)`로 그 작품의 사실을 받습니다(`LIVE_FACTS=per_question`, 기본). 조회한 턴이 질문으로 집계됩니다. `per_artwork`면 작품을 보고할 때 사실을 한 번에 주고 `report_question`으로 질문을 보고합니다.
- 운영 페이지에서 끈 작품은 연결마다 목록에서 빠집니다.

### 서버 설정 (`.env`, 모두 선택)

| 이름 | 기본값 | 뜻 |
| --- | --- | --- |
| `LIVE_MODEL` | `gemini-3.8-live` | Live 모델 |
| `LIVE_VOICE` | `Kore` | 도슨트 목소리 |
| `LIVE_FRAME_POLICY` | `every` | `every`는 사진을 모두 넘기고, `on_speech`는 연결 직후 첫 장과 질문하는 순간의 최신 한 장만 넘깁니다 |
| `LIVE_FACTS` | `per_question` | 사실을 주는 시점. `per_artwork`는 조회 왕복이 없어 질문당 약 1초 빠르다고 코드 주석에 적혀 있습니다(이 문서에서 다시 재지는 않았습니다) |
| `LIVE_RECOGNIZER_FALLBACK` | `off` | `on`이면 Live가 `report_current_artwork`에 `unknown`을 냈을 때 최근 사진 1장을 기준 이미지 검색(`artwork_recognizer.py`)으로 한 번 더 판단합니다. 찾으면 그 작품으로 처리하고 관람 기록의 `via`가 `recognizer`가 됩니다. `uv sync --extra recognition`이 필요하고, 못 불러오면 `unknown`을 유지합니다 |
| `LIVE_PHONE_IDLE_S` | `30` | 폰이 이 초만큼 조용하면 연결을 닫음 |
| `LIVE_START_SENSITIVITY` | `LOW` | 말 시작 감지 민감도(`LOW`·`HIGH`). 짧은 추임새를 덜 잡습니다 |
| `LIVE_SILENCE_MS`, `LIVE_PREFIX_MS` | `700`, `300` | 말이 끝났다고 보는 무음 길이, 말 시작 앞에 붙여 두는 길이(ms) |
| `LIVE_VISIT_LOG` | `off` | 관람 기록. `off`·`team`·`visitor`. 꺼져 있으면 운영 페이지에 아무것도 쌓이지 않습니다 |
| `LIVE_OFF_ARTWORKS` | 비어 있음 | 서버를 켤 때 꺼 둘 작품 ID(쉼표로 구분) |

서버를 켜면 적용된 값을 `[live] model=... voice=...` 한 줄로 보여 줍니다.

### 이 절을 어디까지 확인했나 (11/23)

실제 서버와 Gemini에 붙어 이 절대로 따라 해 16가지를 확인했습니다. push의 모르는 작품 오류와 닫힘, handsfree의 `ready` 칸과 `session_id`, `resumed` 칸, `/live/status` 칸, 인사 턴의 자막·음성, 사진을 보낸 뒤 글 질문의 `artwork` 메시지와 두 번의 `turn_complete`, 같은 `session_id`의 새 연결에 앞 연결이 4000으로 닫힘, END VISIT가 연결을 1000으로 닫음입니다.

**이번에 돌려 보지 않은 것.** 폰이 30초 조용할 때의 4001 닫힘, `interrupted`, `kept_conversation`, push의 `speech_start`, `LIVE_FRAME_POLICY=on_speech`입니다. 이것들은 가짜 Gemini로 하는 `tests/live/test_live_session_lifetime.py`가 다룹니다(실제 Gemini로는 확인하지 않았습니다). `profile`이 말투에 미치는 영향은 코드만 읽었고 어느 쪽으로도 확인하지 않았습니다.

### GET `/live/status` — 연결 상태 (운영 확인용)

받는 값: `active_visits`(접속 중인 관람 수), `visits`(각 항목 `session_id` 앞 4글자·`artwork_id`·`idle_s`·`gemini_connected`·`reconnects`), `saved_resumes`(저장된 재개 정보 수), `model`, `voice`, `frame_policy`. 질문·답변·재개 핸들·전체 세션 ID는 내보내지 않습니다.

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
| `artworks` | 목록 | 작품별 인식 보고 수, 인식 구간, 재방문, 질문 수(사실을 조회한 턴), 말한 턴 수 `speech_turns`, 원라벨 10개, 덩이 3개, 결과 4개, 비교 수, 토큰, 제목, 켜짐·꺼짐 |
| `artworks_without_records` | 목록 | 기간 안에 기록이 없는 작품 ID. 아무도 묻지 않은 작품도 콘텐츠 공백의 신호입니다 |
| `totals` | 객체 | 전체 질문 수와 라벨·덩이·결과 합계, 작품이 비어 있던 질문 수, 보고가 없던 질문 수, 인식 실패 수 |
| `transitions`, `sequences` | 목록 | 작품 간 전환과 관람 순서 |
| `first_audio_ms` | 객체 | 중앙값·p90·재지 못한 수. **관람객이 기다린 시간보다 약 1초 작습니다** |
| `quality`, `end_reasons` | 객체 | 끼어들기·재연결 등과 종료 이유 |
| `warnings` | 목록 | 집계에서 뺀 기록과 이유 |

**비율을 서버가 계산하지 않습니다.** 분자와 분모를 함께 돌려주고 `a/b (p%)` 표기와 분모 0일 때의 `N/A`는 화면이 맡습니다.

주의 둘. `visit`은 **관람 하나**입니다. 폰이 다시 붙어도 한 관람으로 이어 씁니다(11/19 수정). 다만 서버를 다시 켜면 세션이 사라져 새 관람이 됩니다. 작품별 "인식 구간"은 특정 작품 인식부터 다른 작품 인식까지이고 **체류 시간이 아닙니다**.

오류: 400 날짜 형식이 틀림 / 기간이 거꾸로 / 모르는 `source_kind`.

### GET `/api/admin/artworks` — 작품 목록과 켜짐·꺼짐

받는 값: `artworks`(각 항목 `artwork_id`·`title_en`·`on_view`), `off`(꺼진 작품 ID 목록), `note`.

### POST `/api/admin/artworks/{artwork_id}/on_view` — 작품 켜고 끄기

보내는 값: `{"on_view": true}` 또는 `{"on_view": false}`. 받는 값: `changed`(실제로 바뀌었는지)와 위 목록을 함께 돌려줍니다. 오류: 404 모르는 `artwork_id`.

끈 작품은 Live의 도구 값 목록과 전시작 목록, 함수 결과에서 함께 빠지고 그 작품의 비교쌍도 빠집니다. **상태는 메모리에만 있습니다.** 서버를 다시 켜면 `.env`의 `LIVE_OFF_ARTWORKS`만 남고 나머지는 모두 켜집니다. `data/artworks.csv`의 `on_view_status`(FE3가 적는 현장 확인 상태)와는 다른 사실이며 서로 읽지 않습니다. `/api/turn`과 `/api/ask`는 거르지 않습니다. 호출자가 작품 ID를 직접 주는 경로이기 때문입니다.

## 바꿀 때 확인할 곳

| 바꾸는 것 | 함께 고칠 파일 |
| --- | --- |
| `/api/turn`에 보내는 필드 | `server/pre_live/turn.py`의 `turn()`, `static/api.js`의 `postTurn()`, 글라스 앱 |
| `/api/turn`에서 받는 필드 | `server/pre_live/turn.py`의 응답, `server/pre_live/docent_reply.py`의 `DocentReply`, `static/app.js`의 `sendTurn()` |
| 운영 API의 집계 칸 | `server/visit_stats.py`, `server/admin.py`, `static/admin.js`, 이 문서 |
| `/ws/live`의 메시지·설정 | `server/live/live.py`(주고받기), `server/live/live_conversation.py`(`artwork`·`comparison` 메시지), `server/live/live_config.py`(환경 변수), `static/live/live_conversation.js`(폰), `tests/live/test_live_session_lifetime.py`, 이 문서 |
