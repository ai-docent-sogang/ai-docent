# 기준 이미지 DB (작품 인식용)

담당: BE2. 카메라 사진과 비교할 작품 이미지 목록과 벡터입니다(개발계획서 5장 2안).

| 파일 | 내용 | git |
| --- | --- | --- |
| `manifest.csv` | 이미지 1장당 1행. 작품 ID(e뮤지엄 `relicId`), 파일 이름, SHA-256, 제목, 분류, 공공누리 유형, 사용 여부(`rights_use`), 작품 페이지, 확인일 | 올림 |
| `index.npz` | 사용 승인된 이미지의 벡터와 모델 이름·버전 | 올리지 않음(각자 생성) |

이미지 원본(약 1.2GB)은 GitHub에 올리지 않고 팀 Google Drive 폴더로 공유합니다. 각자 받아서 `data/incoming/`에 둡니다(`docent_kb.jsonl`, `images_clean/`). 다른 위치에 두면 `.env`에 `DOCENT_IMAGES_DIR=이미지폴더경로`를 적습니다.

## 만드는 순서 (저장소 최상위 폴더에서)

```bash
uv run python -m tools.build_manifest
```

```bash
uv sync --extra recognition
```

```bash
uv run python -m tools.build_index
```

```bash
uv run python -m server.recognition 찍은사진.jpg
```

1. `build_manifest`: 작품마다 e뮤지엄 페이지에서 공공누리 유형을 읽어 `manifest.csv`를 만들고, 해설을 `data/kb/emuseum_kb.jsonl`로 옮깁니다. 처음에는 1,000장 기준 10분 정도 걸리고, 다시 실행하면 확인한 행은 건너뜁니다.
2. `uv sync --extra recognition`: 인식에 필요한 라이브러리(torch 등, 수백 MB)를 설치합니다. 처음 한 번만 합니다.
3. `build_index`: 사용 승인된 이미지를 벡터로 바꿉니다. 처음에는 모델(DINOv2)을 내려받습니다. `--model openai/clip-vit-base-patch32 --output data/reference/index_clip.npz`로 CLIP과 비교할 수 있습니다.
4. `server.recognition`: 사진 한 장으로 가장 비슷한 작품 3개와 점수를 봅니다.

## 사용 여부 규칙 (`rights_use`)

| 공공누리 | 사용 | 근거 |
| --- | --- | --- |
| 제1유형 | 사용 | 사용자 일괄 승인 (2026-10-31) |
| 제4유형 | 비상업 내부 연구용으로만 사용 | 사용자 승인 (2026-11-03). 변경금지 조건이 있어 이미지를 잘라 내거나 고쳐서 보여 주지 않음 |
| 그 외·표기 없음 | 사용 안 함 | |

같은 이미지가 두 번 있으면(예: `이름(1).jpg`) 하나만 씁니다. 파일 해시가 `manifest.csv`와 다르면 `build_index`가 건너뛰므로, 팀원 모두 같은 이미지 세트를 쓰는지 확인할 수 있습니다.

## 아직 정하지 않은 것

- "이 점수 이상이면 확정" 기준: 회화실 시험 사진으로 정답률을 잰 뒤 정합니다(역할 가이드 4장 인식 기준선 측정).
- 서버(`/api/turn`) 연결: 기준이 정해지면 BE1과 함께 연결합니다. 지금 서버는 이전처럼 Gemini가 작품을 고릅니다.
