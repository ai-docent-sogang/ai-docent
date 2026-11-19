"""질문 유형 라벨과 답변 결과의 단일 출처 (담당 FE1).

관람 중에는 Live가 `report_question` 함수 호출로 라벨을 보고하고, 관람 뒤에는
`tools/classify_questions.py`가 같은 질문을 다시 분류한다. 두 값을 견주려면 정의가
하나여야 하므로 라벨·결과와 그 설명문을 이 파일에만 둔다.

다른 모듈을 가져오지 않는다. 기록 쪽(`server/visit_log.py`)과 Live 쪽
(`server/live_config.py`), 집계 쪽(`server/visit_stats.py`)이 모두 이 파일을 가져온다.
"""

LABELS = ("fact", "artist", "meaning", "context", "technique", "comparison", "navigation", "request",
          "other", "unknown")

# 라벨의 뜻을 한 줄씩 적는다. 사람과 모델이 같은 기준을 보게 하려고 정의를 한곳에 둔다.
LABEL_GUIDE = """fact: asks for a verifiable attribute of the WORK itself (date, size, designation, material, where it is kept).
artist: asks about the PERSON who made it — who they were, their life, career, reputation, or other works.
meaning: asks what something in the picture means or symbolises, or what is happening in the scene.
context: asks why or for whom the work was made, its historical background, or its use. Not about the artist as a person — that is "artist".
technique: asks how it was made: brushwork, pigments, ink handling, composition method, state of preservation.
comparison: asks to compare this work with another work, artist, period, or tradition.
navigation: asks about museum logistics or rules: where something is, opening hours, photography, how to use the app.
request: asks the guide to change how it speaks rather than for new information: shorter, more detail, repeat, slower, another language.
other: a clear question that none of the labels above fit.
unknown: not a question, unintelligible, or impossible to classify."""

OUTCOMES = ("answered", "no_source", "out_of_scope", "unknown")

OUTCOME_GUIDE = """answered: you answered using the FACTS returned by report_current_artwork.
no_source: the question was about this exhibition but the verified facts did not hold the answer, so you said you do not have it.
out_of_scope: the question was not about this exhibition or its artworks.
unknown: you could not tell which of the above applies."""

# 대시보드는 10개를 그대로 늘어놓지 않고 세 덩이로 모아 보여 준다. 원라벨은 기록과 별도 탭에 남는다.
# interest만 작품별 관심 분포의 분모가 된다. 앱 조작 질문은 작품에 대한 궁금증이 아니다.
GROUPS = {
    "interest": ("fact", "artist", "meaning", "context", "technique", "comparison"),
    "control": ("navigation", "request"),
    "unclassified": ("other", "unknown"),
}

_GROUP_OF = {label: group for group, labels in GROUPS.items() for label in labels}

if set(_GROUP_OF) != set(LABELS):
    # 라벨을 더하고 덩이에 넣지 않으면 집계에서 조용히 사라진다. 그래서 가져올 때 바로 터뜨린다.
    raise ValueError(f"GROUPS가 LABELS를 다 덮지 않는다: {sorted(set(LABELS) ^ set(_GROUP_OF))}")


def normalize_label(value) -> str:
    """Live가 보고한 라벨을 목록 안의 값으로 맞춘다. 목록 밖이거나 없으면 "unknown"이다."""
    return _norm(value, LABELS)


def normalize_outcome(value) -> str:
    """Live가 보고한 결과를 목록 안의 값으로 맞춘다. 목록 밖이거나 없으면 "unknown"이다."""
    return _norm(value, OUTCOMES)


def _norm(value, allowed: tuple[str, ...]) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    return text if text in allowed else "unknown"


def group_of(label: str) -> str:
    """라벨이 속한 덩이. 목록 밖의 값은 unknown과 같이 다룬다."""
    return _GROUP_OF.get(label, "unclassified")
