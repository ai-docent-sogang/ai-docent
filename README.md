# AI 도슨트 v0 (11/4 스마트폰 시연)

아이폰 Safari에서 카메라로 그림을 비추고 버튼을 누른 채 영어로 말하면, 노트북 서버가 음성과 카메라 프레임을 Gemini에 보냅니다. 도슨트는 작품을 인식하고, 관람객 프로필에 맞춘 비교 설명을 영어 음성으로 답합니다. 계획 전체는 [`AI_도슨트_개발계획서.md`](AI_도슨트_개발계획서.md)를 참고하세요.

- 방식: 요청-응답(계획서 4장 B안). 녹음된 음성을 Gemini에 직접 넣어 받아쓰기와 답변을 한 번에 받고, 음성 출력은 브라우저 `speechSynthesis`(en-US)로 합니다.
- 작품 인식: 카메라 프레임과 작품 목록을 함께 보내 Gemini가 고릅니다(계획서 5장 1안). 확신이 없으면 `unknown`을 반환하고 관람객에게 다시 묻습니다.
- 개인화: 첫 인사에서 출신 국가와 익숙한 미술을 묻고, 답에서 프로필을 추출합니다. 서버가 프로필 태그로 비교 작품 순서를 정하고 이미 소개한 비교는 뒤로 보냅니다.
- 저장하지 않는 것: 녹음, 카메라 프레임, 세션. 세션은 서버 메모리에만 있다가 서버를 끄면 사라집니다.

## 준비

`docent/` 폴더에서 실행합니다.

```bash
uv sync
```

```bash
cp .env.example .env
```

`.env`에 `GEMINI_API_KEY`를 넣은 뒤(서버가 `docent/.env`를 자동으로 읽습니다), 계정에서 쓸 수 있는 모델 ID를 확인해 `GEMINI_MODEL`에 적습니다. 오디오·이미지 입력을 지원하는 Flash 계열을 권장합니다.

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

## 시연 순서

1. 아이폰에 이어폰을 연결하고 무음 모드를 끕니다. 무음 모드에서는 음성이 나오지 않을 수 있습니다.
2. **Start**를 누르고 카메라·마이크 접근을 허용합니다. 도슨트가 인사하며 출신 국가를 묻습니다.
3. 빨간 버튼을 누른 채 답합니다. 예: "I'm from France and I love Impressionism."
4. 모니터나 인쇄물의 작품을 비추고 버튼을 누른 채 질문합니다. 예: "What am I looking at?", "Can you compare it with something I know?"
5. 화면 하단에서 인식된 작품, 사용된 비교, 프로필, 응답 시간(Gemini / 전체)을 확인합니다. 응답 시간은 계획서의 방식 비교에 기록합니다.

말하기가 어려운 환경에서는 입력창에 질문을 입력해도 됩니다.

## 콘텐츠

시연 작품은 `data/artworks.csv`, 비교 작품은 `data/comparisons.csv`에 있습니다.

| ID | 작품 | 비교 후보 |
| --- | --- | --- |
| `JS_INWANG` | 정선, 인왕제색도 | 세잔 생트빅투아르 산 / 호쿠사이 후가쿠 36경 |
| `KHD_GENRE` | 김홍도, 단원 풍속도첩 | 브뤼헐 / 호쿠사이 망가 |
| `KSH_SELF` | 강세황, 자화상 | 뒤러 자화상(1500) / 렘브란트 말년 자화상 |

**모든 내용은 `unverified` 초안입니다.** 공식 소장품 페이지로 사실과 소장번호를 확인하고, `official_url`·`checked_at`·`verification_status`를 채운 뒤 시연하세요. 도슨트는 이 CSV에 있는 사실만 말하도록 지시되어 있으므로, CSV의 오류는 그대로 음성으로 전달됩니다. 조선 회화실 실제 전시 여부도 별도로 확인해야 합니다.

`key_facts`, `similarities`, `differences`는 `|`로, `profile_tags`는 `;`로 구분합니다. 작품을 추가하면 서버를 다시 시작합니다.
