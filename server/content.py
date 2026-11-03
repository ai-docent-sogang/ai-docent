"""콘텐츠 DB(작품·비교쌍 CSV)를 읽고, 관람객에게 맞는 비교 순서를 정하는 파일.

담당: BE2
같이 보는 파일: data/artworks.csv, data/comparisons.csv (FE3이 작성), tools/check_content.py (CSV 검사)

CSV 안에서 한 칸에 여러 값을 넣을 때의 구분자:
    key_facts, similarities, differences  →  |  (예: "사실 1|사실 2")
    profile_tags                          →  ;  (예: "france;impressionism")
도슨트는 이 CSV에 있는 사실만 말한다. CSV가 틀리면 도슨트도 틀리게 말한다.
CSV는 서버를 켤 때 한 번 읽으므로, 고친 뒤에는 서버를 다시 켠다.
"""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def split_cell(value, separator):
    """"a|b| c" 같은 칸을 ["a", "b", "c"]로 나눈다. 빈 조각은 버린다."""
    return [part.strip() for part in value.split(separator) if part.strip()]


def load_artworks(path=DATA_DIR / "artworks.csv"):
    """작품 CSV를 {artwork_id: 행} 사전으로 읽는다. key_facts는 문장 목록으로 바꾼다.

    서버는 key_facts만 Gemini에 보낸다. unverified_facts 열은 확인되지 않은 문장이라 읽지 않는다.
    """
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["key_facts"] = split_cell(row["key_facts"], "|")
    return {row["artwork_id"]: row for row in rows}


def load_comparisons(path=DATA_DIR / "comparisons.csv"):
    """비교쌍 CSV를 행 목록으로 읽고, 여러 값이 든 칸을 목록으로 바꾼다.

    주의: 아직 verification_status로 거르지 않는다. 미검증 행도 Gemini에 전달된다.
    """
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["profile_tags"] = split_cell(row["profile_tags"], ";")
        row["similarities"] = split_cell(row["similarities"], "|")
        row["differences"] = split_cell(row["differences"], "|")
    return rows


def profile_terms(profile):
    """프로필 값(국가, 익숙한 미술)을 태그 비교용 소문자 단어 집합으로 만든다.

    예: {"country": "France", "familiar_art": ["Post-Impressionism"]}
        → {"france", "post-impressionism", "post", "impressionism"}
    """
    terms = set()
    for value in [profile.get("country", "")] + list(profile.get("familiar_art", [])):
        value = value.lower().strip()
        if value:
            terms.add(value)
            terms.update(value.replace("-", " ").split())
    return terms


def rank_comparisons(comparisons, artwork_id, profile, used_ids):
    """현재 작품의 비교쌍을 관람객에게 맞는 순서로 정렬한다.

    1순위: 아직 소개하지 않은 비교 (이미 쓴 것은 뒤로)
    2순위: profile_tags가 프로필과 많이 겹치는 비교
    """
    terms = profile_terms(profile)
    candidates = [c for c in comparisons if c["artwork_id"] == artwork_id]

    def key(c):
        matches = sum(1 for tag in c["profile_tags"] if tag in terms or tag.replace("-", " ") in terms)
        return (c["comparison_id"] in used_ids, -matches)

    return sorted(candidates, key=key)
