# AI 도슨트 (AIVY)

외국인 관람객이 국립중앙박물관 조선 회화 앞에서 폰 카메라로 그림을 비추고 영어로 물으면, 도슨트가 작품을 알아보고 관람객이 아는 외국 그림과 비교해 답하는 폰 웹앱입니다. 2026-11-18 멘토 전달본과 12/1 시연(서화실 촬영)을 준비하고 있습니다.

계획 전체는 [개발계획서](docs/개발계획서.md), 팀원별 할 일은 [역할 가이드](docs/역할_가이드.md), 지금 어디까지 했는지는 [진행 상황](docs/진행상황.md), 서버와 앱이 주고받는 형식은 [API 약속](docs/api.md)에 있습니다.

## 지금 상태 (2026-11-18)

- **화면**: AIVY(FE2). 관람 시작 → 카메라로 그림 비추기 → Hold to talk로 말하거나 글로 질문 → 인식된 작품 상세 → My visit 요약 → 관람 종료.
- **대화 방식**: 버튼 없는 Live 대화(handsfree, `WS /ws/live`). START EXPLORING을 한 번 누르면 그 뒤로는 말만 하면 됩니다. 마이크 소리는 계속, 카메라 사진은 3초마다 서버로 가고, 서버가 Gemini Live(`gemini-3.8-live`, 목소리 Kore)와 중계합니다. 도슨트가 말하는 도중에 끼어들 수 있습니다. 처음에 Live를 열지 못하면 예전 버튼 방식(`POST /api/turn`, 요청-응답)으로 시작합니다.
- **끊김**: 연결이 끊기면 같은 관람으로 다시 붙고 대화가 이어집니다. 화면 자동 꺼짐을 막고(Wake Lock), Live로 시작한 뒤에는 버튼 방식으로 바꾸지 않습니다. 전원 버튼으로 폰을 잠그면 웹페이지는 멈춥니다(iOS 제한).
- **작품 인식**: Live가 카메라 사진을 보고 시연 11점 중 무엇인지 함수(`report_current_artwork`)로 알립니다. 서버는 그 작품의 검증된 사실과 비교 후보만 돌려주고, 도슨트는 그 안에서만 답합니다. 기준 이미지 검색 방식(`server/recognition.py`, BE2)은 아직 연결 전입니다.
- **개인화와 비교**: 화면의 지역·연령 선택을 연결할 때 프로필로 넘깁니다(값 이름은 11/18 회의에서 맞춤). 도슨트가 비교 작품을 꺼내면 함수(`report_comparison`)나 답 속 제목으로 기록해 요약 화면에 쌓습니다.
- **저장하지 않는 것**: 녹음, 카메라 사진, 세션. 세션은 서버 메모리에만 있다가 서버를 끄면 사라집니다.

## 폴더 구조와 담당

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
│   ├── app.py            API 주소와 요청 처리 (BE1)
│   ├── live.py           Live 음성 중계 /ws/live, /live 시험 페이지 (FE1)
│   ├── live_context.py   Live 지시문 조각(작품 맥락·프로필·비교 후보) (BE1)
│   ├── ask.py            텍스트 질문·답변 API /api/ask (BE1)
│   ├── prompts.py        도슨트 지시문과 첫 인사 (BE1, 말투는 FE3 제안)
│   ├── gemini_client.py  Gemini 호출과 답의 모양 (BE1)
│   ├── session.py        관람 세션 기억 (BE1)
│   ├── content.py        콘텐츠 CSV 읽기와 비교 순서 (BE2)
│   ├── recognition.py    사진으로 작품 후보 찾기 (BE2, 서버 연결 전)
│   └── logs.py           응답 시간·인식 기록 자리 (BE2, 아직 구현 안 됨)
├── static/      폰 웹앱
│   ├── index.html, style.css, app.js
│   │                     AIVY 화면과 흐름 (FE2. FE1의 세션·카메라·녹음 흐름을 그대로 씀)
│   ├── api.js            서버 요청 (FE1, 글라스 앱이 따를 형식)
│   ├── audio.js          녹음 WAV 변환, 음성 출력 (FE1)
│   ├── config.js         서버 주소와 시험용 작품 목록 (FE1)
│   ├── live_conversation.js  버튼 없는 Live 대화: 마이크·사진 전송, 재생, 재연결 (FE1)
│   ├── stt.js            브라우저 음성 인식 (FE1, 화면에는 아직 연결 안 됨)
│   └── live_test.html, live_test.js, live_mic_worklet.js, live_player.js
│                         Live 음성 시험 페이지 /live (FE1, 버튼 방식)
├── glasses/     글라스 앱과 조사 기록 (FE2)
├── data/        콘텐츠 (FE3)
│   ├── artworks.csv, comparisons.csv, comparison_extended.csv
│   ├── scenarios/        대화 시나리오
│   ├── eval/             평가 질문 세트와 측정 결과 (data/eval/README.md)
│   ├── reference/        기준 이미지 목록표와 벡터 (BE2, data/reference/README.md)
│   ├── kb/               e뮤지엄 해설 DB
│   └── incoming/         Drive에서 받은 원본 이미지·해설 (git 제외)
├── tools/       검사·측정·DB 만들기 도구 (담당은 파일마다 다름)
│   ├── build_manifest.py, build_index.py, emuseum_page.py, make_answer_sheet.py
│   │                     이미지 목록표·벡터·인식 정답표 (BE2)
│   ├── check_content.py, eval_recognition.py
│   │                     CSV 검사·인식 정답률 도구 자리 (BE2, 아직 구현 안 됨)
│   ├── compare_modes.py  요청-응답 vs Live 비교 실험 (BE1)
│   ├── live_relay_spike.py, fake_browser_live.py, probe_live_audio.py
│   │                     Live 중계를 따로 띄우는 시험 서버와 측정 (FE1)
│   └── live_frame_recognition.py, classify_questions.py, make_visit_analytics_mock_report.py
│                         관람 분석 측정 (FE1)
├── tests/       시험 (FE1). 실행 방법은 각 파일 맨 위 주석
├── experiments/voice/    음성 비교 실험 코드와 기록 (FE1)
└── .github/rulesets/     main 브랜치 보호 규칙
```

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

**Live 설정**: 서버 환경 변수로 바꿉니다. 모두 비워 두면 아래 기본값입니다. 자세한 것은 [API 약속](docs/api.md)의 `/ws/live` 절과 [멘토 전달 안내](docs/FE1/멘토_전달_안내.md)에 있습니다.

| 변수 | 기본값 | 뜻 |
| --- | --- | --- |
| `LIVE_MODEL` | `gemini-3.8-live` | Live 모델 |
| `LIVE_VOICE` | `Kore` | 목소리(11/18 결정) |
| `LIVE_FRAME_POLICY` | `every` | `every`: 사진을 받는 대로 넘김 / `on_speech`: 말이 시작될 때 한 장만 |
| `LIVE_START_SENSITIVITY` | `LOW` | 말 시작 감지 민감도(`LOW`/`HIGH`) |
| `LIVE_SILENCE_MS` | `700` | 이만큼 조용하면 말이 끝났다고 봄 |
| `LIVE_PREFIX_MS` | `300` | 말로 인정하기 전에 필요한 말소리 길이 |
| `LIVE_PHONE_IDLE_S` | `30` | 폰에서 이 시간 동안 아무것도 안 오면 연결을 닫음(다시 붙으면 대화 이어짐) |

틀린 값을 넣어도 서버는 켜집니다. `[live] LIVE_PHONE_IDLE_S 값이 숫자가 아니라 ...` 처럼 경고 한 줄을 찍고 그 변수만 기본값으로 갑니다. 켤 때 지금 적용된 값을 `Application startup complete.` 바로 앞에 한 줄로 보여 줍니다.

```
[live] model=gemini-3.8-live voice=Kore frame_policy=every start=LOW silence=700ms prefix=300ms idle=30s
```

## 시험

```bash
node tests/test_ask.mjs
node tests/test_live_conversation.mjs
node tests/test_stt.mjs
node tests/test_live_mic.mjs
node tests/test_live_player.mjs
PYTHONPATH=. uv run python tests/test_live_session_lifetime.py
```

서버나 Gemini 없이 돌아갑니다. 콘텐츠 CSV를 고친 뒤에는 검사 도구를 돌립니다: `PYTHONPATH=. uv run python -m tools.check_content` (BE2, 11/18 PR #23). 중복 ID, 없는 `artwork_id`, 구분자, `verification_status`, `checked_at` 형식을 봅니다. 11/18 기준 0 errors, 18 warnings입니다.

## 시연 순서

1. 아이폰에 이어폰을 연결하고 무음 모드를 끕니다. 스피커로도 동작하지만(11/18 실기기에서 스스로 말을 끊지 않았음), 전시실에서는 이어폰을 권합니다.
2. 첫 화면에서 지역과 연령대를 고르고 **START EXPLORING**을 누른 뒤 카메라·마이크 접근을 허용합니다. 도슨트가 먼저 인사하며 어디서 왔는지, 어떤 미술을 좋아하는지 묻습니다. **이제부터는 버튼을 누르지 않고 말하면 됩니다.**
3. 모니터나 인쇄물의 작품을 비추고 질문합니다. 예: "Who painted this?", "Can you compare it with a painting I might know?" 도슨트가 말하는 도중에 말을 걸면 멈추고 새 말에 답합니다.
4. 작품을 알아보면 카메라 위에 **ARTWORK RECOGNIZED** 칩이 뜹니다. 누르면 작품 상세와 쓰인 비교 작품이 나옵니다.
5. 큰 버튼은 음소거 토글입니다(**Listening · tap to mute**). 다른 사람과 이야기할 때 눌러 둡니다.
6. 오른쪽 위 **My visit**에서 이번 관람에서 본 작품과 비교 수를 보고, **END VISIT**으로 관람을 끝냅니다. 서버의 세션도 함께 지워집니다.

**폰을 잠그지 마세요.** 화면 자동 꺼짐은 막지만, 전원 버튼으로 잠그면 웹페이지가 멈춥니다. 짧게 잠갔다 풀면 연결이 그대로이거나 "Reconnecting…" 뒤 이어집니다. 말하기 어려운 환경에서는 입력창에 질문을 입력해도 됩니다.

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

작품 11점과 비교쌍 20건은 모두 FE3 검토를 거쳐 `verification_status=verified`입니다(`checked_at` 2026-11-09). 작품 사실(`key_facts`)은 e뮤지엄 작품 페이지(`official_url`)에서, 비교쌍의 유사점·차이점은 양쪽 작품의 공식 소장품 기록에서 옮겼습니다. 페이지로 확인하지 못한 문장은 `unverified_facts`에 남겼고 서버는 이 열을 읽지 않습니다.

- **서화실 실제 전시 여부(`on_view_status`)는 11점 모두 아직 "확인 필요"입니다.** 시연 전에 현장과 박물관 공식 사이트에서 확인하고, 전시되지 않은 작품은 뺍니다.
- 서버는 아직 `verification_status`로 거르지 않습니다(`server/content.py`). 지금은 모두 verified지만, 검증 안 된 행이 생기면 시연 전에 빼야 합니다.
- 도슨트는 CSV에 있는 내용만 말하도록 지시되어 있으므로, CSV의 오류는 그대로 음성으로 전달됩니다.

`key_facts`, `similarities`, `differences`는 `|`로, `profile_tags`는 `;`로 구분합니다. 작품을 추가하면 서버를 다시 시작합니다.
