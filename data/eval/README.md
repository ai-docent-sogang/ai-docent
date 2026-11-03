# 평가 질문 세트 (FE3 작성, BE1 사용)

`questions.csv`에 [역할 가이드 7장](../../docs/역할_가이드.md)의 "평가 질문 세트 30개"를 채웁니다. 정답이 CSV에 있는 질문 20개와 CSV에 없는 질문 10개입니다.

| 열 | 내용 |
| --- | --- |
| `question_id` | `Q01`처럼 고유한 번호 |
| `question` | 관람객이 할 법한 영어 질문 |
| `artwork_id` | 그 질문을 할 때 보고 있는 작품 |
| `answer_in_csv` | 정답이 콘텐츠 CSV에 있으면 `yes`, 없으면 `no` |
| `expected_answer` | `yes`면 기대하는 답의 핵심, `no`면 "확실하지 않다고 답해야 함" |
| `source_column` | 정답이 들어 있는 CSV와 열 (예: `artworks.csv:key_facts`) |

BE1은 프롬프트를 바꿀 때마다 같은 질문 세트로 전후를 비교합니다. `answer_in_csv=no`인 질문에 사실을 지어내 답하면 실패입니다.

# 인식 시험 사진 정답표 (BE2)

시험 사진 파일은 `data/test_photos/`에 두고 **git에 올리지 않습니다**(관람객 얼굴, 작품 이용 조건). 정답표 `recognition_answers.csv`만 커밋합니다.

| 열 | 내용 |
| --- | --- |
| `photo_file` | `data/test_photos/` 안의 파일 이름 |
| `artwork_id` | 정답 작품의 e뮤지엄 ID(`PS…`, `data/reference/manifest.csv`의 `artwork_id`). 기준 DB에 없는 작품을 일부러 찍었으면 `none` |
| `condition` | 촬영 조건. 예: `monitor-front`, `monitor-45deg`, `print-glare`, `site-glass`, `site-crowd` |
| `taken_by` | 찍은 사람 |
| `taken_at` | 찍은 날짜 |
