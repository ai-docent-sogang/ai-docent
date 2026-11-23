"""작품·비교쌍 CSV 로딩과 프로필에 따른 비교쌍 정렬 (담당 BE2).

CSV를 수정하면 `tools/check_content.py`로 검사한 뒤 서버를 재시작한다.
"""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def split_cell(value, separator):
    return [part.strip() for part in value.split(separator) if part.strip()]


def load_artworks(path=DATA_DIR / "artworks.csv"):
    """작품 ID로 조회할 수 있게 읽고 `key_facts`를 문장 목록으로 변환한다."""
    with open(path, encoding="utf-8-sig") as f:  # Excel CSV의 BOM을 제거한다.
        rows = list(csv.DictReader(f))
    for row in rows:
        row["key_facts"] = split_cell(row["key_facts"], "|")
    return {row["artwork_id"]: row for row in rows}


def load_comparisons(path=DATA_DIR / "comparisons.csv"):
    """비교쌍 CSV의 모든 행을 읽는다. Live는 검증된 행만 사용하며 `/api/turn`은 전체를 사용한다."""
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["profile_tags"] = split_cell(row["profile_tags"], ";")
        row["similarities"] = split_cell(row["similarities"], "|")
        row["differences"] = split_cell(row["differences"], "|")
    return rows


def profile_terms(profile):
    """국가·익숙한 미술 이름을 소문자로 정규화해 전체 이름과 구성 단어를 수집한다."""
    terms = set()
    for value in [profile.get("country", "")] + list(profile.get("familiar_art", [])):
        value = value.lower().strip()
        if value:
            terms.add(value)
            terms.update(value.replace("-", " ").split())
    return terms


def rank_comparisons(comparisons, artwork_id, profile, used_ids):
    """미사용 비교쌍을 우선하고, 같은 그룹에서는 프로필 태그 일치 수로 정렬한다."""
    terms = profile_terms(profile)
    candidates = [c for c in comparisons if c["artwork_id"] == artwork_id]

    def key(c):
        matches = sum(1 for tag in c["profile_tags"] if tag in terms or tag.replace("-", " ") in terms)
        return (c["comparison_id"] in used_ids, -matches)

    return sorted(candidates, key=key)


def build_artwork_context(art):
    """요청·응답 방식(`/api/ask`)과 Live가 함께 쓰는 작품 근거 글을 구성한다.

    보물·국보와 화폭·인물 의상의 혼동을 줄이도록 지정 등급과 화폭 재질을 명시한다
    (11/11 방식 비교 Q03·Q07).
    """
    facts = "\n".join(f"- {fact}" for fact in art["key_facts"])
    designation = art.get("designation") or "none recorded"
    return (
        f"ARTWORK: {art['title_en']}\n"
        f"Artist: {art['artist']}\nDate: {art['date']}\n"
        f"Painting surface: {art['medium']}\nDesignation: {designation}\n"
        f"FACTS (the only facts you may use):\n{facts}"
    )
