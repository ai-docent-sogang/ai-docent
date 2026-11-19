"""관람 기록 집계(server/visit_stats.py) 시험.

담당: FE1. 집계 규칙은 docs/FE1/FE1_관람분석_측정계획.md의 지표 사전을 따른다.

pytest로는 수집되지 않는다. 이렇게 돌린다:
    PYTHONPATH=. uv run python tests/test_visit_stats.py

서버도 Gemini도 부르지 않는다. JSONL을 직접 써 넣고 집계 결과만 본다.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import visit_stats  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  통과 · {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  실패 · {name}" + (f" — {detail}" if detail else ""))


def write(folder, day, lines):
    """`visits-YYYYMMDD.jsonl`에 줄을 덧붙인다. 기록 코드를 거치지 않고 직접 쓴다."""
    path = Path(folder) / f"visits-{day}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def row(visit_id, t, event, source_kind="team_rehearsal", **fields):
    return {"visit_id": visit_id, "t": t, "source_kind": source_kind, "event": event, **fields}


def started(visit_id, bucket, **fields):
    return row(visit_id, 0.0, "visit_start", start_bucket=bucket, season_id="", gallery="",
               ui_lang="en", mode="handsfree", model="m", voice="Kore", **fields)


def question(visit_id, t, artwork_id, label, outcome="answered", first_audio_ms=1800):
    return row(visit_id, t, "question", artwork_id=artwork_id, channel="voice", label=label,
               outcome=outcome, first_audio_ms=first_audio_ms)


print("\n1. 자정을 넘긴 관람 하나를 두 파일에서 모아 한 건으로 센다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261118", [started("v1", "2026-11-18T23:50"),
                            row("v1", 60.0, "artwork_identified", artwork_id="A", via="function")])
    write(tmp, "20261119", [row("v1", 1200.0, "artwork_identified", artwork_id="B", via="function"),
                            row("v1", 1500.0, "visit_end", reason="visit_ended", duration_s=1500,
                                counts={"question": 0})])
    out = visit_stats.collect("2026-11-18", "2026-11-18", "team_rehearsal", folder=Path(tmp))
    check("관람 한 건으로 센다", out["visits"]["total"] == 1, str(out["visits"]))
    check("종료까지 이어 붙인다", out["visits"]["ended"] == 1 and out["visits"]["no_visit_end"] == 0)
    check("두 파일을 모두 읽는다", len(out["range"]["files"]) == 2, str(out["range"]["files"]))
    check("작품 둘이 나온다", {a["artwork_id"] for a in out["artworks"]} == {"A", "B"},
          str([a["artwork_id"] for a in out["artworks"]]))

    after = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    check("시작한 날에만 귀속한다(다음 날 조회에는 없다)", after["visits"]["total"] == 0,
          str(after["visits"]))
    check("귀속 규칙을 응답에 적는다", "visit_start" in out["range"]["attribution"])

print("\n2. 인식 구간은 특정 작품 인식부터 다른 작품 인식까지다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        started("v1", "2026-11-19T10:00"),
        row("v1", 10.0, "artwork_identified", artwork_id="A", via="function"),
        row("v1", 40.0, "artwork_identified", artwork_id="B", via="function"),
        row("v1", 60.0, "artwork_identified", artwork_id="A", via="function"),
        row("v1", 100.0, "visit_end", reason="visit_ended", duration_s=100, counts={}),
    ])
    out = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    by = {a["artwork_id"]: a for a in out["artworks"]}
    check("구간 셋이 생긴다", by["A"]["dwells"] == 2 and by["B"]["dwells"] == 1, str(by.keys()))
    check("A는 30초와 40초를 합쳐 70초", by["A"]["recognized_s"]["total"] == 70.0,
          str(by["A"]["recognized_s"]))
    check("B는 20초", by["B"]["recognized_s"]["total"] == 20.0, str(by["B"]["recognized_s"]))
    check("마지막 구간은 visit_end까지다", by["A"]["recognized_s"]["n"] == 2)
    check("A 재방문 한 번", by["A"]["revisit_dwells"] == 1, str(by["A"]["revisit_dwells"]))
    check("전환 둘(A→B, B→A)", sorted((t["from"], t["to"]) for t in out["transitions"])
          == [("A", "B"), ("B", "A")], str(out["transitions"]))
    check("관람 순서를 남긴다", out["sequences"][0]["path"] == ["A", "B", "A"],
          str(out["sequences"]))

print("\n3. 같은 작품 재보고는 구간을 쪼개지 않고 unknown은 구간을 끊지 않는다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        started("v1", "2026-11-19T10:00"),
        row("v1", 10.0, "artwork_identified", artwork_id="A", via="function"),
        row("v1", 20.0, "artwork_identified", artwork_id="A", via="function"),
        row("v1", 30.0, "artwork_unknown", via="function"),
        row("v1", 40.0, "artwork_identified", artwork_id="A", via="function"),
        row("v1", 70.0, "visit_end", reason="visit_ended", duration_s=70, counts={}),
    ])
    out = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    only = out["artworks"][0]
    check("구간은 하나다", only["dwells"] == 1, str(only["dwells"]))
    check("길이는 10초부터 70초까지 60초", only["recognized_s"]["total"] == 60.0,
          str(only["recognized_s"]))
    check("인식 보고 횟수는 따로 센다", only["identifies"] == 3, str(only["identifies"]))
    check("unknown은 전체에서만 센다", out["totals"]["artwork_unknown"] == 1)
    check("전환은 없다", out["transitions"] == [], str(out["transitions"]))

print("\n4. 종료 기록이 없으면 마지막 줄까지로 보고 하한값으로 표시한다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        started("v1", "2026-11-19T10:00"),
        row("v1", 10.0, "artwork_identified", artwork_id="A", via="function"),
        question("v1", 50.0, "A", "fact"),
    ])
    out = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    only = out["artworks"][0]
    check("종료가 없다고 표시한다", out["visits"]["no_visit_end"] == 1, str(out["visits"]))
    check("마지막 줄까지 40초", only["recognized_s"]["total"] == 40.0, str(only["recognized_s"]))
    check("하한값 구간 수를 따로 센다", only["recognized_s"]["open_ended"] == 1,
          str(only["recognized_s"]))

print("\n5. 자료 종류가 섞여 있어도 요청한 쪽만 센다 (모의와 실측을 합산하지 않는다)")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        started("v1", "2026-11-19T10:00"),
        question("v1", 20.0, "A", "fact"),
        started("v2", "2026-11-19T11:00", source_kind="mock"),
        row("v2", 5.0, "question", source_kind="mock", artwork_id="A", channel="voice",
            label="fact", outcome="answered", first_audio_ms=100),
    ])
    real = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    mock = visit_stats.collect("2026-11-19", "2026-11-19", "mock", folder=Path(tmp))
    check("실측만 센다", real["visits"]["total"] == 1 and real["totals"]["questions"] == 1,
          str(real["visits"]))
    check("모의만 센다", mock["visits"]["total"] == 1 and mock["totals"]["questions"] == 1,
          str(mock["visits"]))
    check("응답에 어느 자료인지 적는다", real["source_kind"] == "team_rehearsal")

print("\n6. 라벨 10개가 세 덩이로 모이고 앱 조작은 관심 분포에서 빠진다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        started("v1", "2026-11-19T10:00"),
        row("v1", 5.0, "artwork_identified", artwork_id="A", via="function"),
        question("v1", 10.0, "A", "fact"),
        question("v1", 20.0, "A", "artist"),
        question("v1", 30.0, "A", "navigation"),
        question("v1", 40.0, "A", "request"),
        question("v1", 50.0, "A", "other"),
        question("v1", 60.0, "A", "unknown", outcome="unknown", first_audio_ms=-1),
        row("v1", 70.0, "visit_end", reason="visit_ended", duration_s=70, counts={}),
    ])
    out = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    only = out["artworks"][0]
    check("관심 덩이는 둘(fact, artist)", only["groups"]["interest"] == 2, str(only["groups"]))
    check("앱 조작 덩이는 둘(navigation, request)", only["groups"]["control"] == 2,
          str(only["groups"]))
    check("분류 실패 덩이는 둘(other, unknown)", only["groups"]["unclassified"] == 2,
          str(only["groups"]))
    check("원라벨 10개를 그대로 남긴다", len(only["labels"]) == 10 and only["labels"]["artist"] == 1,
          str(only["labels"]))
    check("덩이 합이 질문 수와 같다", sum(only["groups"].values()) == only["questions"] == 6,
          str(only["groups"]))
    check("보고가 없던 질문을 따로 센다", out["totals"]["questions_without_report"] == 1,
          str(out["totals"]["questions_without_report"]))
    check("재지 못한 응답 시간을 평균에서 뺀다",
          out["first_audio_ms"]["n"] == 5 and out["first_audio_ms"]["unmeasured"] == 1,
          str(out["first_audio_ms"]))
    check("응답 시간에 체감보다 작다는 주의를 적는다", "1초" in out["first_audio_ms"]["note"])

print("\n7. 묶이지 않는 기록은 버리고 이유를 남긴다")
with tempfile.TemporaryDirectory() as tmp:
    write(tmp, "20261119", [
        row("orphan", 5.0, "question", artwork_id="A", channel="voice", label="fact",
            outcome="answered", first_audio_ms=900),
        started("v1", "2026-11-19T10:00"),
    ])
    out = visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    check("visit_start 없는 묶음은 세지 않는다", out["visits"]["total"] == 1, str(out["visits"]))
    check("버린 이유를 남긴다", any("visit_start" in w for w in out["warnings"]), str(out["warnings"]))
    check("그 질문은 집계에 들어가지 않는다", out["totals"]["questions"] == 0,
          str(out["totals"]["questions"]))
    check("기록이 없으면 분모가 0이고 비율을 만들지 않는다",
          out["first_audio_ms"]["median"] is None and out["visits"]["duration_s"]["n"] == 0,
          str(out["first_audio_ms"]))

print("\n8. 읽기만 한다 (보관 기간 정리를 부르지 않는다)")
with tempfile.TemporaryDirectory() as tmp:
    old = write(tmp, "20200101", [started("old", "2020-01-01T10:00")])
    new = write(tmp, "20261119", [started("v1", "2026-11-19T10:00")])
    visit_stats.collect("2026-11-19", "2026-11-19", "team_rehearsal", folder=Path(tmp))
    check("아주 오래된 파일도 지우지 않는다", old.exists() and new.exists(),
          str(sorted(p.name for p in Path(tmp).iterdir())))

print("\n9. 잘못된 입력은 거부한다")
with tempfile.TemporaryDirectory() as tmp:
    for name, args in (("기간이 거꾸로면 거부한다", ("2026-11-19", "2026-11-18", "team_rehearsal")),
                       ("모르는 자료 종류는 거부한다", ("2026-11-19", "2026-11-19", "visitors")),
                       ("날짜 형식이 틀리면 거부한다", ("11/19", "11/19", "team_rehearsal"))):
        try:
            visit_stats.collect(*args, folder=Path(tmp))
        except ValueError as exc:
            check(name, True, str(exc)[:60])
        else:
            check(name, False, "거부하지 않았다")

print(f"\n관람 집계 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
