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
from server import live_config, visit_log  # noqa: E402
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
    call(c, "lookup_facts", label="artist", outcome="answered")
    c.state["heard"], c.state["said"] = "Who painted this?", "Kim Hong-do did."
    c.remember_turn()
    rows = questions(tmp)
    check("질문 한 건이 남는다", len(rows) == 1, str(len(rows)))
    check("라벨이 붙는다", rows and rows[0]["label"] == "artist", str(rows and rows[0]["label"]))
    check("결과가 붙는다", rows and rows[0]["outcome"] == "answered")

print("\n2. 함수를 부른 직후 말 없는 턴이 먼저 끝나도 라벨이 답변 턴까지 간다(11/20 실측 순서)")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    c.state["heard"] = "Who painted this?"
    call(c, "lookup_facts", label="artist", outcome="answered")
    c.remember_turn()                                    # 도구 호출 턴의 turn_complete. 아직 말이 없다
    check("말이 없는 턴은 질문으로 세지 않는다", len(questions(tmp)) == 0, str(len(questions(tmp))))
    check("그 턴이 끝나도 보고가 남아 있다", c.state["label"] == "artist" and c.state["grounded"] is True,
          str((c.state["label"], c.state["grounded"])))
    c.state["said"] = "Kim Hong-do did."                 # 뒤이어 온 답변
    c.remember_turn()
    rows = questions(tmp)
    check("답변 턴에 라벨과 grounded가 붙는다",
          len(rows) == 1 and rows[0]["label"] == "artist" and rows[0]["grounded"] is True,
          str(rows))
    c.state["heard"], c.state["said"] = "And this one?", "That is Inwang."
    c.remember_turn()
    rows = questions(tmp)
    check("기록하고 나면 다음 질문은 앞 라벨을 물려받지 않는다",
          len(rows) == 2 and rows[1]["label"] == "unknown" and rows[1]["grounded"] is False, str(rows[1:]))

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
    call(c, "lookup_facts", label=" FACT ", outcome="nope")
    c.state["heard"], c.state["said"] = "When?", "1805."
    c.remember_turn()
    rows = questions(tmp)
    check("대소문자와 공백을 다듬는다", rows and rows[0]["label"] == "fact", str(rows and rows[0]["label"]))
    check("목록 밖 결과는 unknown", rows and rows[0]["outcome"] == "unknown")


def result(conversation, name, **args):
    return conversation.answer_tool_call(type("C", (), {"name": name, "args": args})())


print("\n5. 조회한 턴만 grounded다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    got = result(c, "lookup_facts", label="fact")
    check("조회가 작품 사실을 돌려준다", got.get("ok") and "FACTS" in got["facts"], str(got)[:80])
    check("결과에 '이번 질문에만 유효하다'는 안내가 붙는다(후속 질문에서 다시 부르게)",
          "this question only" in got.get("note", ""), str(got.get("note")))
    c.state["heard"], c.state["said"] = "When?", "1805."
    c.remember_turn()
    c.state["heard"], c.state["said"] = "Ha ha, nice.", "Glad you like it."
    c.remember_turn()
    rows = questions(tmp)
    check("조회한 턴은 grounded=True", rows[0]["grounded"] is True, str(rows[0]))
    check("조회하지 않은 턴은 grounded=False", rows[1]["grounded"] is False, str(rows[1]))

print("\n6. 작품을 모르면 사실을 주지 않고 조회로 세지 않는다")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    c.state["artwork_id"] = ""
    got = result(c, "lookup_facts", label="fact")
    check("사실 대신 안내를 돌려준다", got.get("ok") is False and "facts" not in got, str(got)[:80])
    check("grounded를 세우지 않는다", c.state["grounded"] is False)

print("\n7. 작품 보고는 사실을 싣지 않는다(per_question)")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    got = result(c, "report_current_artwork", artwork_id=ARTWORK)
    check("카드에 FACTS가 없다", "FACTS" not in got["artwork"], got["artwork"][:60])

print("\n8. LIVE_FACTS=per_artwork이면 예전 방식으로 돌아간다")
live_config.LIVE_FACTS = "per_artwork"
try:
    with tempfile.TemporaryDirectory() as tmp:
        c = talk(tmp)
        got = result(c, "report_current_artwork", artwork_id=ARTWORK)
        check("작품 보고에 FACTS가 실린다", "FACTS" in got["artwork"])
        result(c, "report_question", label="fact", outcome="answered")
        c.state["heard"], c.state["said"] = "When?", "1805."
        c.remember_turn()
        rows = questions(tmp)
        check("report_question이 grounded 표시가 된다", rows and rows[0]["grounded"] is True)
        names = [f.name for t in live_config.handsfree_tools(relay.artworks, {})
                 for f in t.function_declarations]
        check("도구 선언이 report_question이다", names[-1] == "report_question", str(names))
finally:
    live_config.LIVE_FACTS = "per_question"

print("\n9. 비교로 답한 턴도 질문으로 센다(11/23 결정)")
with tempfile.TemporaryDirectory() as tmp:
    c = talk(tmp)
    got = result(c, "report_comparison", comparison_id="C_KHD_BRUEGEL")
    check("비교 데이터를 돌려준다", got.get("ok") is True, str(got)[:80])
    c.state["heard"], c.state["said"] = "Anything like this abroad?", "Bruegel painted a similar scene."
    c.remember_turn()
    rows = questions(tmp)
    check("grounded=True, 라벨은 comparison",
          len(rows) == 1 and rows[0]["grounded"] is True and rows[0]["label"] == "comparison", str(rows))
    check("outcome은 건드리지 않는다(보고가 없으면 unknown)", rows[0]["outcome"] == "unknown", str(rows[0]))

    c = talk(tmp)
    result(c, "lookup_facts", label="meaning", outcome="answered")
    result(c, "report_comparison", comparison_id="C_KHD_BRUEGEL")
    c.state["heard"], c.state["said"] = "What does it mean, and compare?", "..."
    c.remember_turn()
    rows = questions(tmp)
    check("같은 턴에 lookup_facts 라벨이 있으면 그 라벨을 지킨다", rows[-1]["label"] == "meaning", str(rows[-1]))

    c = talk(tmp)
    got = result(c, "report_comparison", comparison_id="C_NOT_REAL")
    check("거절된 비교는 질문으로 세지 않는다", got.get("ok") is False and c.state["grounded"] is False,
          str(got)[:80])

print(f"\n질문 턴 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
