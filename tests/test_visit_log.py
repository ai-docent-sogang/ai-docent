"""관람 기록(server/visit_log.py) 시험 — 기본값 꺼짐과 "글자를 남기지 않는다"를 지킨다.

담당: FE1. 설계: docs/FE1/관람기록_설계.md

pytest로는 수집되지 않는다. 이렇게 돌린다:

    PYTHONPATH=. uv run python tests/test_visit_log.py

API 키가 없어도 돌아간다. Gemini를 부르지 않는다.
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import visit_log  # noqa: E402

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  통과 · {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  실패 · {label}" + (f" — {detail}" if detail else ""))


def env(**values):
    """환경 변수를 이 시험 동안만 바꾼다. 비운 값은 지운다."""
    for key in [k for k in os.environ if k.startswith("LIVE_VISIT")]:
        del os.environ[key]
    os.environ.update({k: v for k, v in values.items() if v})


def lines(folder):
    out = []
    for path in sorted(Path(folder).glob("visits-*.jsonl")):
        out += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def fake_clock(start=1_800_000_000.0):
    """부를 때마다 0.5초씩 흐르는 시계."""
    state = {"now": start}

    def clock():
        state["now"] += 0.5
        return state["now"]
    return clock, state


print("\n1. 기본값은 꺼짐이다")
with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_DIR=tmp)
    log = visit_log.start(mode="handsfree", model="m", voice="Kore")
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    log.end(reason="phone_closed")
    check("LIVE_VISIT_LOG가 없으면 기록하지 않는다", log.on is False)
    check("파일을 아예 만들지 않는다", list(Path(tmp).iterdir()) == [], str(list(Path(tmp).iterdir())))

with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="off", LIVE_VISIT_DIR=tmp)
    check("off도 꺼짐", visit_log.start(mode="handsfree", model="m", voice="Kore").on is False)

with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="틀린값", LIVE_VISIT_DIR=tmp)
    check("모르는 값이면 켜지 않는다(안전한 쪽)",
          visit_log.start(mode="handsfree", model="m", voice="Kore").on is False)

print("\n2. team으로 켜면 사건이 설계대로 남는다")
with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_SOURCE_KIND="team_rehearsal", LIVE_VISIT_DIR=tmp,
        LIVE_VISIT_SEASON="2026-가을", LIVE_VISIT_GALLERY="서화실")
    clock, _ = fake_clock()
    log = visit_log.start(mode="handsfree", model="gemini-3.8-live", voice="Kore", clock=clock)
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    log.event("question", artwork_id="KHD_SSIREUM", channel="voice", label="", outcome="",
              first_audio_ms=1659)
    log.event("comparison", artwork_id="KHD_SSIREUM", comparison_id="C_KHD_BRUEGEL", via="function")
    log.event("usage", input_audio=1200, input_image=800, input_text=0, output_audio=950, total=2950)
    log.event("quality", issue="interrupted")
    log.end(reason="phone_closed")
    rows = lines(tmp)
    check("사건 7개가 차례로 남는다", [r["event"] for r in rows] == [
        "visit_start", "artwork_identified", "question", "comparison", "usage", "quality", "visit_end"],
        str([r["event"] for r in rows]))
    check("모든 줄에 visit_id·t·source_kind가 있다",
          all({"visit_id", "t", "source_kind"} <= set(r) for r in rows))
    check("visit_id는 서버 세션 ID가 아니라 관람마다 새로 만든 난수다",
          len({r["visit_id"] for r in rows}) == 1 and len(rows[0]["visit_id"]) == 16)
    check("t는 관람 시작부터의 초다(늘어난다)",
          [r["t"] for r in rows] == sorted(r["t"] for r in rows), str([r["t"] for r in rows]))
    check("시즌·전시실을 넣는다", rows[0]["season_id"] == "2026-가을" and rows[0]["gallery"] == "서화실")
    check("끝에 사건 수 합계가 남는다", rows[-1]["counts"]["question"] == 1, str(rows[-1]["counts"]))
    check("관람 길이는 10초 단위로 버린다", rows[-1]["duration_s"] % 10 == 0, str(rows[-1]["duration_s"]))

print("\n3. 글자·소리·사진은 남기지 않는다 (코드가 거부한다)")
with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp)
    clock, _ = fake_clock()
    log = visit_log.start(mode="handsfree", model="m", voice="Kore", clock=clock)

    def refused(label, kind, **fields):
        try:
            log.event(kind, **fields)
        except visit_log.FieldNotAllowed as exc:
            check(label, True, str(exc)[:70])
        else:
            check(label, False, "거부하지 않았다")

    refused("들은 말을 넣으려 하면 거부한다", "question", artwork_id="KHD_SSIREUM",
            heard="Who painted this and when?")
    refused("한 말을 넣으려 하면 거부한다", "question", artwork_id="KHD_SSIREUM",
            said="This painting was created by Kim Hong-do.")
    refused("서버 세션 ID를 넣으려 하면 거부한다", "visit_start", session_id="d2cedb99177d4b32")
    refused("국적·연령대를 넣으려 하면 거부한다", "visit_start", country="France", age_group="adult")
    refused("긴 글자는 칸 이름이 맞아도 거부한다", "question", artwork_id="x" * 65)
    refused("모르는 사건은 거부한다", "visitor_face")
    refused("quality에 모르는 값은 거부한다", "quality", issue="배가 고프다")
    text = "\n".join(p.read_text(encoding="utf-8") for p in Path(tmp).glob("visits-*.jsonl"))
    check("거부된 것은 파일에 한 글자도 들어가지 않았다",
          "Kim Hong-do" not in text and "Who painted" not in text and "France" not in text)
    check("거부해도 관람은 이어진다(그 뒤 사건이 정상으로 남는다)",
          (log.event("artwork_identified", artwork_id="JS_INWANG", via="function") or True)
          and lines(tmp)[-1]["artwork_id"] == "JS_INWANG")

print("\n4. 시각은 10분 단위로 버린다")
check("11:47 → 11:40", visit_log.start_bucket(datetime(2026, 11, 18, 11, 47, 32).timestamp())
      == "2026-11-18T11:40")
check("11:03 → 11:00", visit_log.start_bucket(datetime(2026, 11, 18, 11, 3, 1).timestamp())
      == "2026-11-18T11:00")
check("11:59 → 11:50", visit_log.start_bucket(datetime(2026, 11, 18, 11, 59, 59).timestamp())
      == "2026-11-18T11:50")
with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp)
    clock, _ = fake_clock()
    log = visit_log.start(mode="handsfree", model="m", voice="Kore", clock=clock)
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    log.end()
    rows = lines(tmp)
    check("벽시계 시각은 visit_start의 버킷 하나뿐이다",
          sum("start_bucket" in r for r in rows) == 1 and
          not any(k.endswith(("_at", "_time", "timestamp")) for r in rows for k in r))

print("\n5. 보관 기간이 지난 파일을 지운다")
with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)
    for day in ("20260101", "20261017", "20261019", "20261118"):
        (folder / f"visits-{day}.jsonl").write_text("{}\n", encoding="utf-8")
    (folder / "keep-me.txt").write_text("남의 파일", encoding="utf-8")
    now = datetime(2026, 11, 18, 12, 0).timestamp()
    gone = visit_log.purge_old(folder, 30, now)
    left = sorted(p.name for p in folder.iterdir())
    check("30일보다 오래된 것만 지운다", gone == ["visits-20260101.jsonl", "visits-20261017.jsonl"], str(gone))
    check("경계(30일째)는 남긴다", "visits-20261019.jsonl" in left)
    check("기록이 아닌 파일은 건드리지 않는다", "keep-me.txt" in left, str(left))

print("\n6. 기록이 관람을 멈추게 하지 않는다")
with tempfile.TemporaryDirectory() as tmp:
    blocked = Path(tmp) / "파일인데-폴더로-쓰려-한다"
    blocked.write_text("", encoding="utf-8")
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=str(blocked))
    log = visit_log.start(mode="handsfree", model="m", voice="Kore")
    check("폴더를 못 만들면 조용히 꺼진다(예외를 올리지 않는다)", log.on is False)
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    log.end(reason="phone_closed")
    check("꺼진 기록기에 사건을 넣어도 터지지 않는다", True)

with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp)
    log = visit_log.start(mode="handsfree", model="m", voice="Kore")
    log.end(reason="phone_closed")
    before = len(lines(tmp))
    log.end(reason="두 번째")
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    check("끝난 관람에 또 끝내거나 사건을 넣어도 늘지 않는다", len(lines(tmp)) == before, str(before))

print("\n7. visitor는 source_kind를 visitor로 못 박는다")
with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="visitor", LIVE_VISIT_SOURCE_KIND="mock", LIVE_VISIT_DIR=tmp)
    visit_log.start(mode="handsfree", model="m", voice="Kore").end()
    check("visitor로 켜면 mock이라고 적어도 visitor로 남는다",
          all(r["source_kind"] == "visitor" for r in lines(tmp)))

print("\n8. Gemini 사용량을 usage 사건의 칸으로 바꾼다")


class FakeModality:
    def __init__(self, name):
        self.name = name


class FakeCount:
    def __init__(self, modality, token_count):
        self.modality, self.token_count = modality, token_count


class FakeUsage:
    def __init__(self, total=None, prompt=(), response=()):
        self.total_token_count = total
        self.prompt_tokens_details = list(prompt)
        self.response_tokens_details = list(response)


got = visit_log.usage_fields(FakeUsage(
    total=2950,
    prompt=[FakeCount(FakeModality("AUDIO"), 1200), FakeCount(FakeModality("IMAGE"), 800),
            FakeCount(FakeModality("TEXT"), 40)],
    response=[FakeCount(FakeModality("AUDIO"), 950)]))
check("종류별 숫자를 칸에 나눠 담는다",
      got == {"input_audio": 1200, "input_image": 800, "input_text": 40,
              "output_audio": 950, "total": 2950}, str(got))
check("사용량이 안 오면 전부 0", visit_log.usage_fields(None)
      == {"input_audio": 0, "input_image": 0, "input_text": 0, "output_audio": 0, "total": 0})
check("빈 사용량도 터지지 않는다", visit_log.usage_fields(FakeUsage())["total"] == 0)
got = visit_log.usage_fields(FakeUsage(
    total=10, prompt=[FakeCount(FakeModality("VIDEO"), 7), FakeCount(None, 3)]))
check("모르는 종류는 버리고 전체만 남긴다", got["total"] == 10 and sum(
    v for k, v in got.items() if k != "total") == 0, str(got))
got = visit_log.usage_fields(FakeUsage(
    prompt=[FakeCount("AUDIO", 5), FakeCount("audio", 5)]))
check("같은 종류가 여러 번 와도 더한다(글자로 와도 읽는다)", got["input_audio"] == 10, str(got))

with tempfile.TemporaryDirectory() as tmp:
    env(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp)
    clock, _ = fake_clock()
    log = visit_log.start(mode="handsfree", model="m", voice="Kore", clock=clock)
    log.event("usage", **visit_log.usage_fields(FakeUsage(
        total=100, prompt=[FakeCount(FakeModality("AUDIO"), 60)],
        response=[FakeCount(FakeModality("AUDIO"), 40)])))
    log.end()
    check("usage_fields의 결과가 그대로 usage 사건에 들어간다",
          lines(tmp)[1]["input_audio"] == 60 and lines(tmp)[1]["total"] == 100)


print("\n9. 설계 문서와 코드가 같은 사건을 말한다")
design = (Path(__file__).resolve().parent.parent / "docs/FE1/관람기록_설계.md").read_text(encoding="utf-8")
for kind in visit_log.ALLOWED:
    check(f"설계 문서에 `{kind}`가 적혀 있다", f"`{kind}`" in design)

env()
print(f"\n관람 기록 시험: 통과 {PASS}건, 실패 {FAIL}건")
sys.exit(1 if FAIL else 0)
