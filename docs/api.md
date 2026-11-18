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
| `image` | 아니요 | 파일, JPEG | 말을 끝낸 순간의 카메라 사진 한 장. 웹앱은 가로 최대 1100px로 줄여 보냅니다(`static/app.js`의 `FRAME_MAX_WIDTH`. 11/18에 준한님 요청으로 768px에서 늘렸습니다) |

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

## WS `/ws/live` — 실시간 음성 (Gemini Live API, 11/17 추가 · 11/18 handsfree 추가)

> **FE1 제안, BE1 확인 전(11/18).** 이 절을 11/18 저녁 `server/live.py`·`static/live_conversation.js`와 하나씩 대조해 고쳤습니다. 받는 값 표의 `artwork`·`comparison` 칸, `reconnecting`, 설정 설명, 속 글 로그 문장이 바뀌었습니다. BE1(인우)이 확인하면 이 알림 줄을 지웁니다.

담당: 중계는 FE1(`server/live.py`), 지시문 조각은 BE1(`server/prompts.py`의 `LIVE_INSTRUCTION`, `server/live_context.py`). 경로는 11/17에 BE1과 합의했고, handsfree 형식은 11/18 T1·T2 계약으로 정했습니다.

`tools/live_relay_spike.py`는 운영 서버를 켜지 않고 중계만 띄우는 시험 서버입니다.

AGENTS.md가 클라이언트 코드에 API 키를 넣는 것을 금지하므로 폰이 Gemini Live에 직접 붙을 수 없고, 서버가 가운데서 음성을 중계합니다. 연결은 WebSocket 하나이고, 텍스트 메시지(JSON)와 바이너리 메시지(생 PCM)를 섞어서 주고받습니다.

모드는 첫 메시지의 `"mode"`로 고릅니다.

| 모드 | 쓰는 곳 | 말의 경계 | 작품 |
| --- | --- | --- | --- |
| `"handsfree"` | AIVY 관람객 화면(버튼 없는 대화) | Gemini 자동 음성 감지. 폰은 침묵까지 계속 보냅니다 | Live가 카메라 사진으로 알아보고 함수로 알립니다 |
| `"push"` 또는 없음 | `/live` 시험 페이지(11/17 방식 그대로) | 버튼(`speech_start`·`speech_end`) | 첫 메시지의 `artwork_id`로 고정 |

보내는 값 (폰 → 서버):

| 언제 | 보내는 것 | 형식 |
| --- | --- | --- |
| 연결 직후 1회 (handsfree) | 모드, 이어 쓸 관람 세션, 관람객 프로필 | 텍스트 `{"mode": "handsfree", "session_id": "<POST /api/session 값>", "profile": {"country": "", "age_group": "", "language": "en"}}` — `artwork_id`는 없습니다 |
| 다시 붙을 때 1회 (handsfree) | 폰 화면 꺼짐·네트워크 끊김 뒤 같은 관람으로 | 위와 같고 `"resume": true`를 더합니다. `session_id`는 앞 연결의 `ready`에서 받은 값 |
| 연결 직후 1회 (push) | 어느 작품인지, 프로필, 관람 세션 | 텍스트 `{"artwork_id": "KHD_SSIREUM", "profile": {...}, "session_id": "..."}` |
| 대화하는 내내 (handsfree) | 마이크 소리. **말이 없을 때도 계속** | 바이너리, 16kHz 모노 PCM16 |
| 3초마다 (handsfree) | 카메라 사진 | 텍스트 `{"type": "frame", "jpeg": "<base64, 가로 최대 1100px, 화질 0.7>"}` — 크기·간격·화질의 단일 출처는 `static/live_conversation.js`의 `FRAME_INTERVAL_MS`·`FRAME_MAX_WIDTH`·`FRAME_QUALITY`다. `/api/turn` 경로도 같은 값을 가져다 쓴다 |
| 글로 물을 때 (handsfree) | 글 질문 | 텍스트 `{"type": "text", "text": "..."}` |
| 5초마다 (handsfree) | 살아 있다는 신호 | 텍스트 `{"type": "ping"}` — 서버는 받기만 하고 Gemini로 보내지 않습니다 |
| 버튼 누름 / 누르는 동안 / 뗌 (push) | 말 시작 / 마이크 소리 / 말 끝 | `{"type": "speech_start"}` / 바이너리 16kHz PCM16 / `{"type": "speech_end"}` |

받는 값 (서버 → 폰):

| 받는 것 | 형식 | 폰이 할 일 |
| --- | --- | --- |
| 준비됨 | `{"type": "ready", "model": "...", "mode": "handsfree", "voice": "Kore", "session_id": "..."}` (push는 `"artwork_title"`도 옵니다. `"resume": true`로 붙었을 때만 `"resumed": true/false`가 옵니다) | 대화 시작 표시. `session_id`를 관람 요약에 씁니다 |
| 받아쓴 질문 | `{"type": "heard", "text": "..."}` (조각으로 여러 번) | 관람객 말풍선에 이어 붙임. **마이크로 들은 말만** 옵니다. handsfree 글 질문(`{"type":"text"}`)에는 보내지 않습니다(화면이 직접 그립니다) |
| 답변 음성 | 바이너리, 24kHz 모노 PCM16 | 이어 붙여 재생 |
| 답변 자막 | `{"type": "said", "text": "..."}` (조각) | 도슨트 말풍선에 이어 붙임 |
| 끼어들기 (handsfree) | `{"type": "interrupted"}` | **재생 중인 소리를 즉시 멈춥니다**(관람객이 말을 끊음). 뒤이어 `turn_complete`가 옵니다 |
| 턴 끝 | `{"type": "turn_complete"}` | 다음 말풍선 준비(push는 버튼 다시 활성화) |
| 작품 알아봄 (handsfree) | `{"type": "artwork", "artwork_id": "KHD_SSIREUM", "artwork_title": "...", "artist": "..."}` | 인식 칩·요약에 기록. Live가 함수를 부를 때마다 오므로 같은 작품이 거듭 올 수 있습니다 |
| 비교 꺼냄 (handsfree) | `{"type": "comparison", "comparison_id": "C_KHD_BRUEGEL", "artwork_id": "KHD_SSIREUM", "source": "function", "foreign_title": "...", "foreign_artist": "...", "foreign_collection": "...", "foreign_url": "..."}` | 요약·상세의 비교에 누적. `source`는 `function`(Live가 함수로 알림) 또는 `transcript`(함수 없이 말한 비교를 서버가 답변 받아쓰기에서 찾음) |
| 재연결 중 | `{"type": "reconnecting"}`, 또는 `{"type": "reconnecting", "kept_conversation": true/false}` | "잠시만요" 안내 |
| 다시 붙음 | `{"type": "reconnected", "kept_conversation": true/false, ...ready와 같은 필드}` | 대화 재개 |
| 오류 | `{"type": "error", "message": "..."}` | 안내 문구. AIVY 화면은 기존 `/api/turn` 버튼 방식으로 되돌아갑니다 |

`artwork`의 `artist`와 `comparison`의 `foreign_*` 네 칸은 11/18에 더했습니다. 화면(`static/app.js`)이 같은 값을 손으로 베껴 두고 있었는데, 예원님이 `data/comparisons.csv`를 7점에서 20점으로 늘릴 때 베낀 목록이 어긋났습니다(14점이 요약에서 사라지고 ID 하나는 죽었습니다). 그래서 **화면이 그릴 값은 서버가 보냅니다.** 설명 재료(`angle`·`similarities`·`differences`)는 Gemini에게만 주고 폰에는 보내지 않습니다. 폰 쪽은 받은 칸을 이름으로 추려 담지 않습니다(`static/live_conversation.js`) — 서버가 칸을 더해도 조용히 버려지지 않게 하기 위해서입니다.

`profile`과 `session_id`는 없어도 됩니다. `profile`은 FE2 초기 설정값 세 필드이고(없으면 영어·성인으로 말합니다), **세션 중간에 바꾸지 않습니다**(11/17 BE1 결정). 지역은 `country`로 보냅니다(폰이 보내는 값, `static/app.js`). 지시문을 만드는 `server/live_context.py`는 `region`이라는 이름도 받지만, 함수 결과의 `comparison_ids` 순서를 만드는 `server/live.py`는 `country`만 봅니다. 그래서 `region`만 보내면 두 순서가 어긋날 수 있습니다(11/18 확인, `region: japan`에서 실제로 어긋났습니다). **`country`로 보내 주세요.**

`session_id`는 `POST /api/session`에서 받은 값입니다. 보내지 않거나 서버를 다시 켜서 없어진 ID면 서버가 새로 만들어 `ready`에 담아 돌려줍니다. `kept_conversation`이 거짓이면 앞 대화가 이어지지 않으므로 폰은 안내 문구를 바꿉니다. `reconnecting`에는 이 칸이 없을 때가 있습니다. Gemini 세션을 떠날 때 보내는 `reconnecting`에는 들어 있고, 재연결하는 동안 폰이 보낸 글 질문(push는 버튼 신호)을 받아 "지금은 못 보낸다"고 알리는 `reconnecting`에는 없습니다. 폰은 없으면 모르는 것으로 보고 안내 문구를 그대로 둡니다.

다시 붙기(`"resume": true`, 11/18 오후): 서버는 `session_id`별로 Gemini 재개 핸들과 지금 작품을 메모리에 남겨 둡니다(폰 WS가 끊겨도 지우지 않고, 마지막 갱신 뒤 2시간이 지나면 버립니다. 공식 문서상 핸들 유효 시간). 폰이 같은 `session_id`와 `"resume": true`로 다시 붙으면:

- 핸들로 Gemini 대화를 이으면 `ready.resumed = true`이고, Live는 인사하지 않습니다. 앞 대화를 기억합니다.
- 핸들이 없거나 2시간이 지났거나 거부되면(재시도 3번 뒤) 새 대화로 시작하고 `ready.resumed = false`입니다. 이때 Live는 처음 인사 대신 "다시 연결됐다"고 한 문장만 말하고, 저장된 작품이 있으면 그 작품의 사실로 이어 말합니다(카메라가 다른 작품을 보이면 함수로 바뀝니다).
- 핸들로 다시 붙는 데 실패해 재시도하는 동안에는 `ready` 전이므로 `reconnecting`을 보내지 않습니다. 실제 Gemini에서 끊은 뒤 `ready`까지 약 2초였습니다.
- 같은 `session_id`로 WS가 이미 붙어 있으면 앞 연결을 닫습니다(닫힘 코드 4000).
- handsfree에서 폰이 30초(`LIVE_PHONE_IDLE_S`) 동안 아무것도(소리·사진·글·ping) 보내지 않으면 죽은 연결로 보고 닫습니다(닫힘 코드 4001). Gemini 세션은 정리하고 재개 핸들은 남기므로, 폰은 `"resume": true`로 다시 붙으면 됩니다. 11/18 실기기에서 잠금 해제 뒤 Safari가 페이지를 새로 불렀는데 서버가 앞 WS의 끝을 알지 못한 일이 있어 더했습니다. push 모드에는 적용하지 않습니다.
- 서버를 다시 켜면 저장한 핸들은 사라집니다.

Live 서버 설정(환경 변수, 형식은 바뀌지 않음). `LIVE_MODEL`과 `LIVE_VOICE`는 두 모드가 함께 쓰고, 나머지 다섯 개는 handsfree에만 씁니다. 틀린 값이나 빈 값을 넣으면 그 변수만 기본값으로 갑니다(서버는 켜집니다). 숫자 칸(`LIVE_SILENCE_MS`·`LIVE_PREFIX_MS`·`LIVE_PHONE_IDLE_S`)에 숫자가 아닌 값을, 고르는 칸(`LIVE_START_SENSITIVITY`·`LIVE_FRAME_POLICY`)에 목록 밖의 값을 넣으면 서버 로그에 경고 한 줄이 남습니다. **`LIVE_MODEL`과 `LIVE_VOICE`는 비워 두어도 경고 없이 조용히 기본값으로 갑니다** — 오타를 눈치채지 못할 수 있으니 아래 설정 줄로 확인하세요. 켤 때 지금 적용된 값을 `[live] model=... voice=... frame_policy=... start=... silence=...ms prefix=...ms idle=...s` 한 줄로 찍습니다. API 키는 찍지 않습니다.

| 변수 | 기본 | 뜻 |
| --- | --- | --- |
| `LIVE_MODEL` | `gemini-3.8-live` | Live 음성 모델. `/api/turn`·`/api/ask`가 쓰는 `GEMINI_MODEL`과 다릅니다 |
| `LIVE_VOICE` | `Kore` | Live 목소리 이름(11/13 팀 규칙). 두 모드가 같은 목소리를 씁니다 |
| `LIVE_START_SENSITIVITY` | `LOW` | 말 시작 감지 민감도(`LOW`/`HIGH`). LOW가 짧은 추임새를 덜 잡습니다 |
| `LIVE_SILENCE_MS` | `700` | 이만큼 조용하면 말이 끝났다고 봅니다(공식 문서 권장 500~800) |
| `LIVE_PREFIX_MS` | `300` | 말로 인정하기 전에 필요한 말소리 길이 |
| `LIVE_FRAME_POLICY` | `every` | `every`: 사진을 받는 대로 넘김. `on_speech`: 최신 1장만 들고 있다가 관람객 말이 시작될 때(그 턴의 첫 받아쓰기)와 글 질문 때 1장, Gemini 연결 직후 첫 1장만 넘김 |
| `LIVE_PHONE_IDLE_S` | `30` | 폰 무입력이 이 초를 넘으면 연결을 닫음 |

관람 기록(`server/visit_log.py`)의 환경 변수 여섯 개(`LIVE_VISIT_LOG` 등)는 이 표에 없습니다. 서버가 파일에 남기는 내용이고 폰과 주고받는 형식이 아니므로 이 문서 범위가 아닙니다. [`docs/FE1/관람기록_설계.md`](FE1/관람기록_설계.md)에 변수와 남기는 사건 8종이 적혀 있습니다. 기본값은 꺼짐이라 켜지 않으면 파일을 만들지 않습니다.

`said`에서 말이 아닌 표시(`<no speech>`, `{pause}`, 폭 없는 문자)는 빼고 보냅니다. 남는 말이 없으면 그 조각은 보내지 않습니다.

`said`에 Live의 **속 글**이 섞여 오는 턴이 있습니다(11/18 실측, `gemini-3.8-live`). 말소리에는 없고 받아쓰기에만 `-=call:report_current_artwork{artwork_id:unknown`, `---(No function call needed…)---`, `==========` 같은 토막이 따라옵니다. 가로줄·등호가 이어진 토막이나 함수 이름이 보이면 **그 턴의 남은 `said`를 보내지 않고** 관람 기억에도 넣지 않습니다. 걸러 낸 글은 서버 로그에 `[live] 모델 속 글이 답변 받아쓰기에 섞여 와서 걸러 냈다: '…' + 뒤에 N자` 줄로 남습니다. **글 전체는 남지 않습니다.** 표시 앞 32자만 적고 나머지는 글자 수만 적습니다. 표시 뒤에는 도슨트가 관람객에게 한 말이 이어져 있는데, 서버 출력을 파일로 넘기면 그 말이 저장되기 때문입니다(AGENTS.md: 음성은 처리에만 쓰고 저장하지 않는다). 32자는 가장 긴 표시(`report_current_artwork`, 22자)가 다 보이는 길이입니다. 표시도 함수 이름도 없는 토막(다른 언어 낱말 등)은 거르지 못합니다.

`ready`의 `voice`는 그 연결에 쓰는 목소리 이름입니다. 위 표의 `LIVE_VOICE`로 고릅니다.

handsfree에서 서버가 하는 일 (형식에 영향을 주는 것만):

- **연결되면 Live가 먼저** 짧게 인사하고 어디서 왔는지, 어떤 미술을 좋아하는지 묻습니다. 폰은 브라우저 음성으로 따로 인사하지 않습니다(목소리 하나로 통일).
- **인사 턴 동안에는 사진을 Live에 넣지 않습니다**(정책과 무관). 인사가 끝나거나 관람객이 말을 시작하면 그동안 들고 있던 최신 1장을 바로 넘깁니다. 인사와 사진을 함께 넣으면 Live가 `report_current_artwork` 쪽으로 끌려가 속 글을 흘렸습니다(11/18 실측: 사진 있음 3/3, 사진 없음 1/3).
- Live는 **지금 함수 두 개만** 부릅니다. BE1의 [`docs/BE1_함수호출_설계.md`](BE1_함수호출_설계.md)는 세 개(`report_no_source`, `report_out_of_scope`, `report_comparison`)를 적어 두었지만, `server/live.py`가 Live 설정에 선언한 것은 `report_current_artwork`와 `report_comparison`입니다. `report_no_source`와 `report_out_of_scope`는 아직 없습니다(아래 "아직 없는 것"). 어느 쪽이 맞는지는 BE1·FE1이 함께 정합니다.
- `report_current_artwork(artwork_id)`(11점 ID 또는 `"unknown"`)를 부르면 서버가 그 작품의 확인된 사실과 비교 후보를 돌려주고 폰에 `artwork`를 보냅니다. `"unknown"`이면 `artwork`를 보내지 않고 Live가 관람객에게 그림을 비춰 달라고 합니다. `report_comparison(comparison_id)`는 지금 작품의 검증된 비교쌍만 받고, 받으면 폰에 `comparison`을 보냅니다.
- Live가 비교를 말하면서 `report_comparison`을 부르지 않는 턴이 있습니다(11/18 실측). 그래서 턴이 끝날 때 그 턴에 함수가 없었으면, 답변 받아쓰기에 **지금 작품의** 검증된 비교쌍 제목(대소문자·따옴표·관사·악센트 무시, 괄호 안 다른 이름과 "also known as" 이름 포함)이 나오는지 봅니다. 나오면 함수로 온 것과 똑같이 누적·기록하고 `comparison`(`"source": "transcript"`)을 보냅니다. 10자보다 짧거나 한 단어인 제목은 작가 이름도 함께 나와야 인정합니다. 이미 누적된 비교는 다시 보내지 않습니다.
- 턴이 끝나면 `session.record_turn`에 들은 말(글 질문이면 그 원문), 지금 작품, 이번 턴에 보고된 비교를 남깁니다. 그래서 handsfree 경로에서는 요약 화면의 비교 수가 채워집니다(push는 여전히 0).
- 사진과 소리는 Gemini에 넘기기만 하고 저장하지 않습니다.

push에서 형식에 영향을 주는 약속:

- **자동 음성 감지(VAD)를 끄고** `activity_start`·`activity_end`로 말의 경계를 Gemini에 알립니다. 버튼을 누르는 동안만 소리를 보내므로 모델에 침묵이 전달되지 않아 말의 끝을 알 수 없습니다. 섞어 쓰면 첫 턴만 동작합니다.
- **말의 앞뒤에 300ms 무음**을 넣습니다. 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘립니다(11/11 측정에서 완전 일치 10/25 → 25/25).

구현 내부 사정(큐 분리, `session.receive()` 재호출, 세션 수명 처리)은 이 문서 범위가 아닙니다. `server/live.py` 머리말과 [`docs/11-18_통합_인터페이스.md`](11-18_통합_인터페이스.md) 1장을 보세요.

아직 없는 것:

| 없는 것 | 지금 상태 |
| --- | --- |
| 작품 변경 (push) | 연결 직후 `artwork_id`를 한 번 받고 고정합니다. handsfree는 Live가 사진으로 바꿉니다 |
| 비교쌍 사용 기록 (push) | push는 `comparison_id`를 빈 값으로 남깁니다. handsfree는 함수 호출로 받습니다 |
| 에코 처리 | 서버에서 다루지 않습니다. handsfree는 마이크를 계속 열어 두므로 스피커 소리를 마이크가 다시 들으면 Live가 자기 말에 끼어들 수 있습니다(이어폰 또는 브라우저 echoCancellation 전제) |
| 대화 중 프로필 반영 | 관람객이 말로 출신을 알려 줘도 비교 후보의 순서는 첫 메시지의 `profile`로 정합니다 |
| 여러 관람객 동시 접속 | 단일 세션입니다. 인증도 없습니다(11/13 결정, 12/1 범위) |
| 10분 넘는 연결 | 세션 수명 처리는 모의 시험까지만 확인했고 실기기 확인은 아직입니다 |
| `report_no_source` · `report_out_of_scope` (handsfree) | BE1 설계([`docs/BE1_함수호출_설계.md`](BE1_함수호출_설계.md))에는 있지만 `server/live.py`가 선언하지 않습니다. 못 답한 질문은 폰으로도 관람 기록으로도 나가지 않습니다 — 관람 기록의 `question.outcome`이 빈 값인 이유입니다 |
| 질문 유형 라벨 (handsfree) | 관람 기록의 `question.label`이 빈 값입니다. 라벨 체계는 FE3가 정합니다 |

## 바꿀 때 확인할 곳

| 바꾸는 것 | 함께 고칠 파일 |
| --- | --- |
| 보내는 필드 | `server/app.py`의 `turn()`, `static/api.js`의 `postTurn()`, 글라스 앱 |
| 받는 필드 | `server/app.py`의 응답, `server/gemini_client.py`의 `DocentReply`, `static/app.js`의 `sendTurn()` |
| 실시간 음성(Gemini Live API) 주고받는 형식 | 위 [WS `/ws/live`](#ws-wslive--실시간-음성-gemini-live-api-1117-추가--1118-handsfree-추가) 절, `server/live.py`, `static/live_conversation.js`(handsfree, AIVY 화면), `static/live_test.js`(push, `/live` 시험 페이지), `static/live_mic_worklet.js`, `static/live_player.js` (전환은 11/11 회의에서 확정) |
