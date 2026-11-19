"""무엇을 질문으로 세는지와 라벨 위생을 본다 (server/live_conversation.py).

담당: FE1. 11/19 실측에서 질문 36건이 집계됐으나 작품은 둘만 봤다. 세는 기준이 느슨하다.
이 파일은 그 기준을 바꿀 때 기대를 고정하는 자리다.

pytest로는 수집되지 않는다. 이렇게 돌린다:
    PYTHONPATH=. uv run python tests/test_question_turn.py

Gemini와 서버를 부르지 않는다. LiveConversation의 메서드를 직접 부른다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tests.sandbox  # noqa: F401  실제 기록 폴더에 쓰지 않게 막는다

import server.session as sessions  # noqa: E402
from server import live as relay  # noqa: E402
from server import visit_log  # noqa: E402
from server.live_conversation import LiveConversation  # noqa: E402

PASS = FAIL = 0
ARTWORK = "KHD_SSIREUM"


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  통과 · {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  실패 · {name}" + (f" — {detail}" if detail else ""))


def talk(folder):
    """기록을 켠 대화 하나. 관람 기록은 folder에 쌓인다."""
    os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=folder,
                      LIVE_VISIT_SOURCE_KIND="team_rehearsal")
    log = visit_log.start(mode="handsfree", model="m", voice="Kore")
    return LiveConversation(mode="handsfree", artwork_id=ARTWORK, profile={},
                            visit=sessions.create_session(), artworks=relay.artworks,
                            comparisons=relay.comparisons, resume_store={}, vlog=log)


def questions(folder):
    rows = []
    for path in sorted(Path(folder).glob("visits-*.jsonl")):
        rows += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r["event"] == "question"]


def call(conversation, name, **args):
    conversation.answer_tool_call(type("C", (), {"name": name, "args": args})())


print("\n1. 보고한 라벨이 그 턴의 질문에 붙는다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    call(c, "report_question", label="artist", outcome="answered")
    c.state["heard"], c.state["said"] = "Who painted this?", "Kim Hong-do did."
    c.remember_turn()
    rows = questions(tmp)
    check("질문 한 건이 남는다", len(rows) == 1, str(len(rows)))
    check("라벨이 붙는다", rows and rows[0]["label"] == "artist", str(rows and rows[0]["label"]))
    check("결과가 붙는다", rows and rows[0]["outcome"] == "answered")

print("\n2. 말이 없는 턴의 보고는 다음 질문으로 새지 않는다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    call(c, "report_question", label="meaning", outcome="answered")
    c.state["heard"], c.state["said"] = "mm-hmm", ""      # 모델이 아무 말도 하지 않은 턴
    c.remember_turn()
    check("말이 없으면 질문으로 세지 않는다", len(questions(tmp)) == 0, str(len(questions(tmp))))
    c.state["heard"], c.state["said"] = "And this one?", "That is Inwang."
    c.remember_turn()
    rows = questions(tmp)
    check("다음 질문은 앞 턴의 라벨을 물려받지 않는다",
          len(rows) == 1 and rows[0]["label"] == "unknown", str(rows and rows[0]["label"]))

print("\n3. 보고가 없으면 unknown으로 남는다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    c.state["heard"], c.state["said"] = "Tell me more.", "Of course."
    c.remember_turn()
    rows = questions(tmp)
    check("라벨이 unknown", rows and rows[0]["label"] == "unknown")
    check("결과가 unknown", rows and rows[0]["outcome"] == "unknown")

print("\n4. 목록 밖 값과 대소문자는 다듬어진다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    call(c, "report_question", label=" FACT ", outcome="nope")
    c.state["heard"], c.state["said"] = "When?", "1805."
    c.remember_turn()
    rows = questions(tmp)
    check("대소문자와 공백을 다듬는다", rows and rows[0]["label"] == "fact", str(rows and rows[0]["label"]))
    check("목록 밖 결과는 unknown", rows and rows[0]["outcome"] == "unknown")

print(f"\n질문 턴 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
