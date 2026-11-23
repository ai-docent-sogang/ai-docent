# AI 도슨트 (AIVY)

외국인 관람객이 국립중앙박물관 조선 회화 앞에서 폰 카메라로 그림을 비추고 영어로 물으면, 도슨트가 작품을 알아보고 관람객이 아는 외국 그림과 비교해 답하는 폰 웹앱입니다. 2026-11-18 멘토 전달본과 12/1 시연(서화실 촬영)을 준비하고 있습니다.

계획 전체는 [개발계획서](docs/개발계획서.md), 팀원별 할 일은 [역할 가이드](docs/역할_가이드.md), 지금 어디까지 했는지는 [진행 상황](docs/진행상황.md), 서버와 앱이 주고받는 형식은 [API 약속](docs/api.md)에 있습니다.

## 지금 상태 (2026-11-18, main 기준)

- **화면**: AIVY(FE2). 관람 시작 → 카메라로 그림 비추기 → Hold to talk로 말하거나 글로 질문 → 인식된 작품 상세 → My visit 요약 → 관람 종료.
- **대화 방식**: 요청-응답(`POST /api/turn`). 녹음(16kHz WAV)·사진·글을 Gemini에 한 번에 보내 받아쓰기, 작품 판단, 답변을 받고, 답은 브라우저 `speechSynthesis`(en-US)로 읽어 줍니다.
- **Live 실시간 음성**: 11/11 회의에서 본선으로 정했습니다. 중계는 아직 `tools/live/live_relay_spike.py` 시험대(포트 8013, `/live` 시험 페이지)에 있고, 운영 서버(`server/app.py`)에 붙이는 작업은 진행 중입니다(main에 아직 없음).
- **작품 인식**: 사진과 작품 목록을 함께 보내 Gemini가 고릅니다(계획서 5장 1안). 확신이 없으면 `unknown`을 돌려줍니다. 기준 이미지 검색 방식(`server/recognition.py`, BE2)은 아직 서버에 연결 전입니다.
- **개인화**: 첫 인사에서 출신 국가와 익숙한 미술을 묻고, 대화에서 프로필을 뽑아 비교 작품 순서를 정합니다. 화면의 지역·연령 선택은 아직 서버로 가지 않습니다.
- **저장하지 않는 것**: 녹음, 카메라 사진, 세션. 세션은 서버 메모리에만 있다가 서버를 끄면 사라집니다.

## 폴더 구조와 담당

대화 방식이 둘이라 코드를 방식별로 나눠 두었습니다.

- **`live/`**: Live 실시간 음성(WebSocket `/ws/live`). 본선입니다.
- **`pre_live/`**: Live 이전의 요청·응답 방식(`POST /api/turn`, `POST /api/ask`, 브라우저 STT·TTS). Live가 끊길 때의 대체 경로이기도 합니다.
- 두 폴더 밖에 있는 파일은 두 방식이 함께 쓰거나(`content.py`, `session.py`, `gemini_client.py`의 `make_client`), 대화 방식과 상관없는 것(인식, 관람 기록, 운영 화면)입니다.

`server/`, `static/`, `tests/`, `tools/`가 모두 같은 이름의 하위 폴더 `live/`·`pre_live/`를 가집니다. 방식 하나만 보려면 그 폴더 넷만 열면 됩니다.

```text
ai-docent/  (저장소 최상위)
├── AGENTS.md, CLAUDE.md   팀 공통 작업 지침, AI 코딩 도구용 안내
├── .env.example           .env 견본 (실제 .env는 git 제외)
├── docs/
│   ├── 개발계획서.md, 역할_가이드.md, 진행상황.md, 시연_체크리스트.md
│   ├── api.md             서버와 앱이 주고받는 형식 (BE1·FE1)
│   ├── 11-18_통합_인터페이스.md   11/18 전달본에서 각자 내보내는 형식
│   ├── meeting/           회의록, 작업 안내, 요청 문서
│   └── FE1/               FE1 측정·검토 기록 (음성, 응답 시간, Live, 아이폰 시험, 관람 분석과 모의 데이터)
├── server/      Python 서버
│   ├── app.py            라우터 연결, 세션 시작·끝(/api/session), 첫 화면 (BE1)
│   ├── live/             [Live] 중계와 지시문
│   │   ├── live.py            WebSocket 중계 /ws/live, /live 시험 페이지 (FE1)
│   │   ├── live_config.py     Live 설정, 함수 선언, 지시문 조립 (FE1)
│   │   ├── live_context.py    작품·비교 후보를 지시문에 넣는 글 (BE1)
│   │   ├── live_conversation.py  한 관람의 대화 상태, 함수 호출 응답 (FE1)
│   │   └── live_transcript.py    받아쓰기 정리, 답 속 비교작 찾기 (FE1)
│   ├── pre_live/         [Live 이전] 요청·응답 방식
│   │   ├── ask.py             텍스트 질문·답변 /api/ask (BE1)
│   │   ├── turn.py            한 턴 대화 /api/turn (BE1)
│   │   └── docent_reply.py    /api/turn의 Gemini 호출과 답의 모양 (BE1)
│   ├── prompts.py        도슨트 지시문과 첫 인사. 방식별 지시문이 한 파일에 구역으로 나뉨 (BE1, 말투는 FE3 제안)
│   ├── gemini_client.py  Gemini 클라이언트 만들기. 두 방식이 함께 씀 (BE1)
│   ├── session.py        관람 세션 기억 (BE1)
│   ├── content.py        콘텐츠 CSV 읽기, 비교 순서, 작품 근거 글 (BE2)
│   ├── visit_log.py, visit_stats.py, question_labels.py, on_view.py, admin.py
│   │                     관람 기록·집계·운영 화면. 대화 방식과 무관 (FE1)
│   ├── recognition.py, artwork_crop.py, artwork_recognizer.py, catalog.py
│   │                     사진으로 작품 후보 찾기 (BE2, 서버 연결 전)
│   └── logs.py           응답 시간·인식 기록 자리 (BE2, 아직 구현 안 됨)
├── static/      폰 웹앱
│   ├── index.html, style.css, app.js
│   │                     AIVY 화면과 흐름. 두 방식의 흐름이 app.js 한 파일에 같이 있음 (FE2. FE1의 세션·카메라·녹음 흐름을 그대로 씀)
│   ├── api.js            서버 요청 (FE1, 글라스 앱이 따를 형식)
│   ├── config.js         서버 주소와 시험용 작품 목록 (FE1)
│   ├── admin.html, admin.js  운영 화면 (FE1)
│   ├── live/             [Live] live_conversation.js, live_mic_worklet.js, live_player.js, live_test.html, live_test.js
│   └── pre_live/         [Live 이전] audio.js(녹음 WAV 변환·음성 출력), stt.js(브라우저 음성 인식, 화면에는 아직 연결 안 됨)
├── glasses/     글라스 앱과 조사 기록 (FE2)
├── data/        콘텐츠 (FE3)
│   ├── artworks.csv, comparisons.csv, comparison_extended.csv
│   ├── scenarios/        대화 시나리오
│   ├── eval/             평가 질문 세트와 측정 결과 (data/eval/README.md)
│   ├── reference/        기준 이미지 목록표와 벡터 (BE2, data/reference/README.md)
│   ├── kb/               e뮤지엄 해설 DB
│   └── incoming/         Drive에서 받은 원본 이미지·해설 (git 제외)
├── tools/       검사·측정·DB 만들기 도구 (담당은 파일마다 다름)
│   ├── live/             [Live] live_relay_spike.py(중계 시험대, 포트 8013), fake_browser_live.py, probe_live_audio.py, live_frame_recognition.py (FE1)
│   ├── compare_modes.py  요청-응답 vs Live 비교 실험. 두 방식을 함께 다룸 (BE1)
│   ├── build_manifest.py, build_index.py, emuseum_page.py, make_answer_sheet.py
│   │                     이미지 목록표·벡터·인식 정답표 (BE2)
│   ├── check_content.py, eval_recognition.py
│   │                     CSV 검사·인식 정답률 도구 자리 (BE2, 아직 구현 안 됨)
│   └── classify_questions.py, make_visit_analytics_mock_report.py
│                         관람 분석 측정 (FE1)
├── tests/       시험 (FE1). 실행 방법은 각 파일 맨 위 주석
│   ├── live/             [Live] 세션 수명, 질문 턴, 관람 식별, 화면 대화·마이크·재생
│   ├── pre_live/         [Live 이전] test_ask.mjs(/api/ask 요청), test_stt.mjs(음성 인식 처리)
│   └── sandbox.py, test_admin_*, test_on_view.py, test_visit_log.py, test_visit_stats.py
│                         공통·운영·기록 시험
├── experiments/voice/    음성 비교 실험 코드와 기록 (FE1)
└── .github/rulesets/     main 브랜치 보호 규칙
```

**옛 경로를 찾는다면.** 2026-11-23에 파일을 옮겼습니다. 11/23 이전에 쓴 문서(진행상황, 회의록, 측정 기록)에 적힌 경로는 그대로 두었습니다. 아래로 바꿔 읽으면 됩니다.

| 옛 경로 | 새 경로 |
| --- | --- |
| `server/live*.py` | `server/live/live*.py` |
| `server/ask.py` | `server/pre_live/ask.py` |
| `server/app.py`의 `/api/turn` | `server/pre_live/turn.py` |
| `server/gemini_client.py`의 `DocentReply`, `ask_docent` | `server/pre_live/docent_reply.py` |
| `server/ask.py`의 `build_artwork_context` | `server/content.py` |
| `static/live_*` | `static/live/live_*` |
| `static/audio.js`, `static/stt.js` | `static/pre_live/` |
| `tools/live_relay_spike.py` 등 Live 도구 4개 | `tools/live/` |
| `tests/test_live_*`, `test_question_turn`, `test_visit_identity` | `tests/live/` |
| `tests/test_ask.mjs`, `tests/test_stt.mjs` | `tests/pre_live/` |

각 파일 맨 위 주석에 담당, 하는 일, 같이 보는 파일이 적혀 있습니다.

## 준비

저장소 최상위 폴더에서 실행합니다.

```bash
uv sync
```

```bash
cp .env.example .env
```

`.env`에 `GEMINI_API_KEY`를 넣은 뒤(서버가 이 폴더의 `.env`를 자동으로 읽습니다), 계정에서 쓸 수 있는 모델 ID를 확인해 `GEMINI_MODEL`에 적습니다. 오디오·이미지 입력을 지원하는 Flash 계열을 권장합니다.

```bash
uv run python -m server.gemini_client --list-models
```

Live 시험대를 쓰려면 WebSocket 패키지를 함께 설치합니다.

```bash
uv sync --extra live
```

## 실행

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

아이폰 Safari는 HTTPS 주소에서만 카메라와 마이크를 허용합니다. 다음 두 방법 중 하나를 사용합니다.

**A. Cloudflare 임시 터널 (권장)**: 인증서 설정이 필요 없고 LTE에서도 접속됩니다. 다른 터미널에서 실행한 뒤 출력된 `https://….trycloudflare.com` 주소를 아이폰에서 엽니다.

```bash
cloudflared tunnel --url http://localhost:8000
```

**B. 같은 Wi-Fi + 자체 서명 인증서**: `<노트북 IP>`를 실제 주소로 바꿔 인증서를 만들고 HTTPS로 실행합니다. 아이폰에서 `https://<노트북 IP>:8443`를 열고 경고 화면에서 "웹 사이트 방문"을 누릅니다.

```bash
mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -days 30 -keyout certs/key.pem -out certs/cert.pem -subj "/CN=docent" -addext "subjectAltName=IP:<노트북 IP>"
```

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
```

**Live 시험대**: 운영 서버와 별개로 포트 8013에 띄웁니다. 터널도 8013으로 걸고 아이폰에서 `/live`를 엽니다. 시험 절차는 [아이폰 시험](docs/FE1/FE1_아이폰_시험.md)에 있습니다.

```bash
PYTHONPATH=. uv run uvicorn --app-dir tools/live live_relay_spike:app --port 8013
```

## 시험

```bash
node tests/pre_live/test_ask.mjs
node tests/pre_live/test_stt.mjs
node tests/live/test_live_mic.mjs
node tests/live/test_live_player.mjs
PYTHONPATH=. uv run python tests/live/test_live_session_lifetime.py
```

서버나 Gemini 없이 돌아갑니다. 콘텐츠 CSV 검사 도구(`tools/check_content.py`)는 아직 구현되지 않았습니다. CSV를 고친 뒤에는 서버를 다시 켜서 직접 확인합니다.

## 시연 순서

1. 아이폰에 이어폰을 연결하고 무음 모드를 끕니다. 무음 모드에서는 음성이 나오지 않을 수 있습니다.
2. 첫 화면에서 지역과 연령대를 고르고 **START EXPLORING**을 누른 뒤 카메라·마이크 접근을 허용합니다. 도슨트가 인사하며 어디서 왔는지, 어떤 미술을 좋아하는지 묻습니다.
3. **Hold to talk**를 누른 채 답합니다. 예: "I'm from France and I love Impressionism."
4. 모니터나 인쇄물의 작품을 비추고 버튼을 누른 채 질문합니다. 예: "What am I looking at?", "Can you compare it with something I know?"
5. 작품을 알아보면 카메라 위에 **ARTWORK RECOGNIZED** 칩이 뜹니다. 누르면 작품 상세와 쓰인 비교 작품이 나옵니다.
6. 오른쪽 위 **My visit**에서 이번 관람에서 본 작품과 비교 수를 보고, **END VISIT**으로 관람을 끝냅니다. 서버의 세션도 함께 지워집니다.

말하기가 어려운 환경에서는 입력창에 질문을 입력해도 됩니다. 카메라가 작품이 아닌 곳을 비추고 있으면 작품 이름을 말해도 `unknown`이 나올 수 있으니, 질문할 때는 그림을 비춥니다.

## 콘텐츠

시연 작품은 `data/artworks.csv`, 비교 작품은 `data/comparisons.csv`에 있습니다.

| ID | 작품 (국립중앙박물관 소장품번호) | 비교 작품 |
| --- | --- | --- |
| `JS_INWANG` | 정선, 인왕제색도 (건희 1) | 세잔 「생트빅투아르 산」(Met) / 호쿠사이 「개풍쾌청」(Met) |
| `KHD_SSIREUM` | 김홍도, 씨름 《단원 풍속도첩》 (본관 6504-22) | 브뤼헐 「농민의 결혼식」(KHM) / 호쿠사이 망가(Met) |
| `KHD_SEODANG` | 김홍도, 서당 《단원 풍속도첩》 (본관 6504-23) | 브뤼헐 「아이들의 놀이」(KHM) |
| `KSH_SELF` | 강세황 초상 자필본 (구 10562) | 렘브란트 「63세의 자화상」(내셔널갤러리) / 뒤러 「모피 옷을 입은 자화상」(바이에른 주립회화컬렉션) |
| `KJH_SEHAN` | 김정희, 세한도 (증 10000) | 없음 |
| `LIM_GANGSAN` | 이인문, 강산무진도 (덕수 927) | 없음 |
| `KHD_CHUSEONG` | 김홍도, 추성부도 (건희 16) | 없음 |
| `SYB_BABY` | 신윤복, 아기 업은 여인 (덕수 2291-13) | 없음 |
| `CHAEKGADO_6` | 책가도 6곡병 (건희 4123) | 없음 |
| `LA_DOGS` | 이암, 어미개와 강아지 (본관 255) | 없음 |
| `SSD_CHOCHUNG` | 전 신사임당, 초충도 (신수 3550) | 없음 |

작품 11점과 비교쌍 7건은 모두 FE3 검토를 거쳐 `verification_status=verified`입니다(`checked_at` 2026-11-09). 작품 사실(`key_facts`)은 e뮤지엄 작품 페이지(`official_url`)에서, 비교쌍의 유사점·차이점은 양쪽 작품의 공식 소장품 기록에서 옮겼습니다. 페이지로 확인하지 못한 문장은 `unverified_facts`에 남겼고 서버는 이 열을 읽지 않습니다.

- **서화실 실제 전시 여부(`on_view_status`)는 11점 모두 아직 "확인 필요"입니다.** 시연 전에 현장과 박물관 공식 사이트에서 확인하고, 전시되지 않은 작품은 뺍니다.
- 서버는 아직 `verification_status`로 거르지 않습니다(`server/content.py`). 지금은 모두 verified지만, 검증 안 된 행이 생기면 시연 전에 빼야 합니다.
- 도슨트는 CSV에 있는 내용만 말하도록 지시되어 있으므로, CSV의 오류는 그대로 음성으로 전달됩니다.

`key_facts`, `similarities`, `differences`는 `|`로, `profile_tags`는 `;`로 구분합니다. 작품을 추가하면 서버를 다시 시작합니다.
