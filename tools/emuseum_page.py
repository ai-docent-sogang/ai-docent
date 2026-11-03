"""e뮤지엄 작품 페이지에 보이는 기본정보와 공공누리(KOGL) 표기를 읽는다.

담당: BE2
같이 보는 파일: tools/build_manifest.py (작품마다 이 함수로 이용 조건을 확인함)

API 응답에는 이용 조건이 없어서, 작품 페이지(https://www.emuseum.go.kr/detail?relicId=...)에
사람이 보는 표기("제 1유형 : 출처표시" 등)를 그대로 읽어 기록한다. 페이지 모양이 바뀌면 값이 빈칸으로 나온다.
"""

import html
import re

PAGE_URL = "https://www.emuseum.go.kr/detail?relicId={}"
# 페이지의 "이름표 → 다음 줄 값" 구조에서 읽을 항목
LABELS = {"명칭": "page_title", "국적/시대": "page_nationality_period", "분류": "page_classification", "재질": "page_material"}


def page_lines(page):
    """HTML에서 스크립트·스타일과 태그를 걷어 내고, 보이는 글자만 줄 단위로 돌려준다."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_object_page(page):
    """첫 번째 상세정보 묶음만 읽는다. 페이지에 없는 항목은 빈칸으로 둔다.

    page_kogl_type: "1"~"4" (공공누리 유형 번호). 표기가 없으면 "".
    """
    lines = page_lines(page)
    fields = {name: "" for name in [*LABELS.values(), "page_kogl_type", "page_rights_statement"]}
    for index, line in enumerate(lines[:-1]):
        key = LABELS.get(line)
        if key and not fields[key]:
            fields[key] = lines[index + 1]
        match = re.fullmatch(r"제\s*(\d)\s*유형\s*:.*", line)
        if match and not fields["page_kogl_type"] and lines[index + 1].startswith("저작권 보호분야"):
            fields["page_kogl_type"] = match.group(1)
            fields["page_rights_statement"] = f"{line} / {lines[index + 1]}"
    return fields


def fetch_object_page(relic_id, session):
    response = session.get(PAGE_URL.format(relic_id), timeout=30)
    response.raise_for_status()
    return parse_object_page(response.text)
