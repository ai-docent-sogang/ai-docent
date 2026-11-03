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
