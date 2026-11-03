# 작품 해설 DB

`emuseum_kb.jsonl`은 `tools/build_manifest.py`가 Drive의 `docent_kb.jsonl`을 옮긴 것입니다. 한 줄에 작품 하나이며 `id`(e뮤지엄 `relicId`), `name`, `author`, `desc`(e뮤지엄 해설 원문, 한국어)에 출처(`source`, `object_page_url`)와 복사일(`copied_at`)을 붙였습니다.

- 박물관 원문이지만 **팀 검수 전**입니다. 시연 작품은 FE3가 검수한 `../artworks.csv`의 사실을 우선합니다.
- 해설은 한국어라 도슨트가 영어로 말할 때 번역 오류가 생길 수 있습니다. 서버에 연결할 때 이 점을 표시합니다.
- `artworks.csv`의 작품은 `official_url`의 `relicId`로 이 파일과 연결됩니다(예: 씨름 = `PS0100100100100650400022`).
