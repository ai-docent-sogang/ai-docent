"""작품·비교쌍 CSV를 읽고, 관람객 프로필에 맞춰 비교 후보 순서를 정한다."""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_artworks(path=DATA_DIR / "artworks.csv"):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["key_facts"] = [s.strip() for s in row["key_facts"].split("|") if s.strip()]
    return {row["artwork_id"]: row for row in rows}


def load_comparisons(path=DATA_DIR / "comparisons.csv"):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["profile_tags"] = [t.strip() for t in row["profile_tags"].split(";") if t.strip()]
        row["similarities"] = [s.strip() for s in row["similarities"].split("|") if s.strip()]
        row["differences"] = [s.strip() for s in row["differences"].split("|") if s.strip()]
    return rows


def profile_terms(profile):
    """프로필 값(국가, 익숙한 미술)을 태그 비교용 소문자 단어 집합으로 만든다."""
    terms = set()
    for value in [profile.get("country", "")] + list(profile.get("familiar_art", [])):
        value = value.lower().strip()
        if value:
            terms.add(value)
            terms.update(value.replace("-", " ").split())
    return terms


def rank_comparisons(comparisons, artwork_id, profile, used_ids):
    """현재 작품의 비교쌍을 프로필 일치 수가 많은 순으로, 이미 쓴 것은 뒤로 보낸다."""
    terms = profile_terms(profile)
    candidates = [c for c in comparisons if c["artwork_id"] == artwork_id]

    def key(c):
        matches = sum(1 for tag in c["profile_tags"] if tag in terms or tag.replace("-", " ") in terms)
        return (c["comparison_id"] in used_ids, -matches)

    return sorted(candidates, key=key)
