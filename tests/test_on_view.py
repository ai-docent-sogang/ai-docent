"""작품 켜기/끄기(server/on_view.py) 시험.

담당: FE1. 끈 작품이 Live의 인식 후보와 비교쌍에서 함께 빠지는지 본다.

pytest로는 수집되지 않는다. 이렇게 돌린다:
    PYTHONPATH=. uv run python tests/test_on_view.py

서버도 Gemini도 부르지 않는다. 모듈 수준 목록과 LiveConversation만 쓴다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.session as sessions  # noqa: E402
from server import live as relay  # noqa: E402
from server import on_view, visit_log  # noqa: E402
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


def conversation(artworks):
    """끈 작품을 뺀 목록으로 대화를 하나 만든다. live.py가 넘기는 것과 같은 모양이다."""
    return LiveConversation(mode="handsfree", artwork_id="", profile={},
                            visit=sessions.create_session(), artworks=artworks,
                            comparisons=relay.comparisons, resume_store={},
                            vlog=visit_log.NullLog())


print("\n1. 기본은 전부 켜짐이다")
os.environ.pop("LIVE_OFF_ARTWORKS", None)
on_view.reset_from_env()
check("꺼진 작품이 없다", on_view.OFF == set(), str(on_view.OFF))
check("모든 작품이 보인다", len(on_view.visible(relay.artworks)) == len(relay.artworks),
      f"{len(relay.artworks)}점")
check("작품 하나는 켜져 있다", on_view.is_on(ARTWORK))

print("\n2. .env의 LIVE_OFF_ARTWORKS를 켤 때 읽는다")
os.environ["LIVE_OFF_ARTWORKS"] = f" {ARTWORK} , LA_DOGS ,, "
on_view.reset_from_env()
check("쉼표로 나누고 공백을 다듬는다", on_view.OFF == {ARTWORK, "LA_DOGS"}, str(on_view.OFF))
check("빈 조각은 버린다", "" not in on_view.OFF)
os.environ.pop("LIVE_OFF_ARTWORKS", None)
on_view.reset_from_env()

print("\n3. 끄면 인식 후보에서 빠지고 받은 목록은 그대로다")
before_artworks = len(relay.artworks)
before_comparisons = len(relay.comparisons)
on_view.set_on(ARTWORK, False)
visible = on_view.visible(relay.artworks)
check("꺼진 작품은 보이지 않는다", ARTWORK not in visible)
check("나머지는 그대로 보인다", len(visible) == before_artworks - 1, f"{len(visible)}점")
check("받은 목록을 고치지 않는다", ARTWORK in relay.artworks)
# 모듈 수준 목록을 건드리면 relay.comparisons를 직접 읽는 기존 시험이 깨진다.
check("relay.artworks·relay.comparisons의 길이가 그대로다",
      len(relay.artworks) == before_artworks and len(relay.comparisons) == before_comparisons,
      f"{len(relay.artworks)}점 · {len(relay.comparisons)}쌍")

print("\n4. 끈 작품의 비교쌍도 함께 빠진다")
off_pairs = [c["comparison_id"] for c in relay.comparisons if c.get("artwork_id") == ARTWORK]
check("그 작품에 비교쌍이 있다(시험이 의미를 가진다)", len(off_pairs) > 0, str(off_pairs))
talk = conversation(visible)
check("꺼진 작품의 비교쌍은 쓰이지 않는다",
      all(cid not in talk.verified_comparisons for cid in off_pairs), str(off_pairs))
check("켜진 작품의 비교쌍은 남는다", len(talk.verified_comparisons) > 0,
      f"{len(talk.verified_comparisons)}쌍")
all_on = conversation(on_view.visible(relay.artworks) | {ARTWORK: relay.artworks[ARTWORK]})
check("다시 켜면 그 비교쌍이 돌아온다",
      all(cid in all_on.verified_comparisons for cid in off_pairs), str(off_pairs))

print("\n5. 다시 켜면 되돌아온다")
on_view.set_on(ARTWORK, True)
check("켜짐으로 돌아온다", on_view.is_on(ARTWORK) and ARTWORK in on_view.visible(relay.artworks))

print("\n6. 운영 화면이 쓸 목록은 켜짐·꺼짐을 함께 돌려준다")
on_view.set_on(ARTWORK, False)
rows = on_view.rows(relay.artworks)
by = {r["artwork_id"]: r for r in rows}
check("작품 수가 맞는다", len(rows) == len(relay.artworks), f"{len(rows)}줄")
check("꺼진 작품은 on_view가 False", by[ARTWORK]["on_view"] is False, str(by[ARTWORK]))
check("제목을 함께 준다", bool(by[ARTWORK]["title_en"]), str(by[ARTWORK]["title_en"])[:40])
check("켜진 작품은 True", all(r["on_view"] for r in rows if r["artwork_id"] != ARTWORK))

on_view.OFF.clear()   # 다른 시험을 오염시키지 않는다
print(f"\n작품 켜기/끄기 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
