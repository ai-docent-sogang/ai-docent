"""Live 음성 세션에 넣을 시스템 지시문을 만든다 (11/18 전달본, BE1 → FE1 중계).

담당: BE1
같이 보는 파일: prompts.py (LIVE_INSTRUCTION), ask.py (build_artwork_context, /api/ask와 공유),
              content.py (비교쌍 읽기·정렬, BE2), docs/11-18_통합_인터페이스.md 3장

중계 쪽(FE1)은 이 함수가 돌려준 문자열을 Live 연결의 system_instruction에 그대로 넣기만 한다.
지시문 내용을 바꿔도 중계 코드는 고치지 않는다.

    from server.live_context import build_live_instruction
    system_instruction = build_live_instruction(art, comparisons, profile)

profile은 초기 설정값 {country 또는 region, age_group, language} (FE2, 통합 인터페이스 5장). 비어 있어도 된다.
화면 선택값(region: north-america·europe·china·japan, age_group: 10-19 … 60+)을 그대로 받는다.
세션 중간에 프로필을 바꾸지 않는다(11/18 범위): 연결할 때 한 번만 넣는다.
비교 후보는 verification_status가 verified인 것만 넣는다.

미리 보기: uv run python -m server.live_context KHD_SSIREUM europe 20-29
"""

import sys

from .ask import build_artwork_context
from .content import load_artworks, load_comparisons, rank_comparisons
from .prompts import LIVE_INSTRUCTION

# 화면(FE2)의 지역 선택값·국가 이름 → 비교쌍 profile_tags에 쓰인 태그. rank_comparisons가 이 단어로 비교 순서를 정한다.
# 화면 값: north-america / europe / china / japan (static/index.html region-select, 11/15 FE2).
# 태그는 FE3의 comparisons.csv에 맞췄다(europe, asia, japan, usa, uk 등). 목록을 바꾸면 여기도 고친다.
REGION_TAGS = {
    "north-america": ["usa"], "europe": ["europe"], "china": ["china", "asia"], "japan": ["japan", "asia"],
    "france": ["france", "europe"], "germany": ["germany", "europe"], "netherlands": ["netherlands", "europe"],
    "belgium": ["belgium", "europe"], "italy": ["italy", "europe"], "spain": ["spain", "europe"],
    "uk": ["uk", "europe"], "united kingdom": ["uk", "europe"],
    "usa": ["usa"], "united states": ["usa"], "america": ["usa"], "canada": ["usa"],
    "taiwan": ["asia"], "vietnam": ["asia"],
}

# 화면 값을 사람이 읽는 이름으로 (지시문에 적을 때)
REGION_NAMES = {"north-america": "North America", "europe": "Europe", "china": "China", "japan": "Japan"}

# 연령대 → 말하기 방식. 화면 값(10-19 … 60+)과 단어(child·teen·adult·senior)를 모두 받는다.
AGE_STYLE = {
    "child": "The visitor is a child: use very simple words, short sentences, a warm tone, and ask what they can spot.",
    "teen": "The visitor is a teenager: use clear everyday words and a lively tone.",
    "adult": "The visitor is an adult: use clear, natural language.",
    "senior": "The visitor is a senior: speak calmly and clearly, at a slightly slower pace.",
}
AGE_GROUPS = {"10-19": "teen", "20-29": "adult", "30-39": "adult", "40-49": "adult", "50-59": "adult", "60+": "senior"}

# 언어 코드와 화면의 언어 이름을 모두 받는다. 11/18 전달본은 영어.
LANGUAGES = {"en": "English", "ko": "Korean", "zh": "Chinese", "ja": "Japanese",
             "english": "English", "korean": "Korean", "chinese": "Chinese", "japanese": "Japanese"}

MAX_COMPARISON_OPTIONS = 2  # 한 작품에 제안할 비교 후보 수. 많이 주면 모델이 섞어 말한다.


def home_of(profile):
    """프로필에서 지역·국가 값을 꺼낸다. 화면은 region, 통합 인터페이스는 country라 둘 다 본다."""
    return (profile.get("region") or profile.get("country") or "").strip()


def profile_block(profile):
    """초기 설정값을 지시문에 넣을 글로 바꾼다. 없는 값은 적지 않는다(추측하지 않게)."""
    home = home_of(profile)
    age = (profile.get("age_group") or profile.get("age") or "").strip().lower()
    age = AGE_GROUPS.get(age, age)
    language = LANGUAGES.get((profile.get("language") or "en").strip().lower(), "English")
    lines = [f"- Speak in {language}."]
    if home:
        name = REGION_NAMES.get(home.lower(), home)
        lines.append(f"- Home region or country: {name}. Use this only to choose which comparison to offer first.")
    lines.append(f"- {AGE_STYLE.get(age, 'Age group unknown: use clear, natural language.')}")
    return "VISITOR PROFILE:\n" + "\n".join(lines)


def comparison_block(comparisons, artwork_id, profile, used_ids=()):
    """이 작품의 검증된 비교 후보를 관람객에게 맞는 순서로 최대 2개 적는다."""
    verified = [c for c in comparisons if c.get("verification_status", "").strip().lower() == "verified"]
    home = home_of(profile).lower()
    ranking_profile = {"country": home, "familiar_art": REGION_TAGS.get(home, [])}
    ranked = rank_comparisons(verified, artwork_id, ranking_profile, set(used_ids))[:MAX_COMPARISON_OPTIONS]
    if not ranked:
        return "COMPARISON OPTIONS: none for this painting."
    parts = []
    for i, c in enumerate(ranked, 1):
        parts.append(
            f"{i}. {c['foreign_title']} by {c['foreign_artist']} ({c['foreign_date']}, {c['foreign_collection']})\n"
            f"   Angle: {c['angle']}\n"
            f"   Similarities: {' / '.join(c['similarities'])}\n"
            f"   Differences: {' / '.join(c['differences'])}"
        )
    return "COMPARISON OPTIONS (offer option 1 first):\n" + "\n".join(parts)


def build_live_instruction(art, comparisons, profile=None, used_ids=()):
    """Live 세션 system_instruction 전체 문자열: 규칙 + 작품 맥락 + 프로필 + 비교 후보."""
    profile = profile or {}
    return "\n\n".join([
        LIVE_INSTRUCTION,
        build_artwork_context(art),
        profile_block(profile),
        comparison_block(comparisons, art["artwork_id"], profile, used_ids),
    ])


if __name__ == "__main__":
    artwork_id = sys.argv[1] if len(sys.argv) > 1 else "KHD_SSIREUM"
    profile = {"country": sys.argv[2] if len(sys.argv) > 2 else "",
               "age_group": sys.argv[3] if len(sys.argv) > 3 else "", "language": "en"}
    print(build_live_instruction(load_artworks()[artwork_id], load_comparisons(), profile))
