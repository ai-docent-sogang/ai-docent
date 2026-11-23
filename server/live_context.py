"""Live 시스템 지시문과 초기 관람객 프로필 구성 (담당 BE1).

미리 보기: uv run python -m server.live_context KHD_SSIREUM europe 20-29
"""

import sys

from .content import build_artwork_context, load_artworks, load_comparisons, rank_comparisons
from .prompts import LIVE_INSTRUCTION

# 화면의 지역·국가 값을 `data/comparisons.csv`의 profile_tags에 맞춘다.
REGION_TAGS = {
    "north-america": ["usa"], "europe": ["europe"], "china": ["china", "asia"], "japan": ["japan", "asia"],
    "france": ["france", "europe"], "germany": ["germany", "europe"], "netherlands": ["netherlands", "europe"],
    "belgium": ["belgium", "europe"], "italy": ["italy", "europe"], "spain": ["spain", "europe"],
    "uk": ["uk", "europe"], "united kingdom": ["uk", "europe"],
    "usa": ["usa"], "united states": ["usa"], "america": ["usa"], "canada": ["usa"],
    "taiwan": ["asia"], "vietnam": ["asia"],
}

REGION_NAMES = {"north-america": "North America", "europe": "Europe", "china": "China", "japan": "Japan"}

AGE_STYLE = {
    "child": "The visitor is a child: use very simple words, short sentences, a warm tone, and ask what they can spot.",
    "teen": "The visitor is a teenager: use clear everyday words and a lively tone.",
    "adult": "The visitor is an adult: use clear, natural language.",
    "senior": "The visitor is a senior: speak calmly and clearly, at a slightly slower pace.",
}
AGE_GROUPS = {"10-19": "teen", "20-29": "adult", "30-39": "adult", "40-49": "adult", "50-59": "adult", "60+": "senior"}

LANGUAGES = {"en": "English", "ko": "Korean", "zh": "Chinese", "ja": "Japanese",
             "english": "English", "korean": "Korean", "chinese": "Chinese", "japanese": "Japanese"}

MAX_COMPARISON_OPTIONS = 2  # 모델이 여러 작품의 정보를 섞지 않도록 후보 수를 제한한다.


def home_of(profile):
    """웹앱의 `region`을 우선하고 통합 인터페이스의 `country`도 지원한다."""
    return (profile.get("region") or profile.get("country") or "").strip()


def profile_block(profile):
    """초기 관람객 프로필을 언어·지역·연령대 지시문으로 구성한다."""
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
    """검증된 비교 후보를 관람객 프로필에 맞춰 정렬해 제시한다."""
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
    """선택된 작품의 근거·비교 후보와 초기 프로필을 지시문에 합친다."""
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
