"""운영 API(server/ops.py) 시험.

담당: FE1. 집계 조회와 작품 켜기/끄기가 서버를 거쳐 동작하는지 본다.

pytest로는 수집되지 않는다. 이렇게 돌린다:
    PYTHONPATH=. uv run python tests/test_ops_api.py

Gemini를 부르지 않는다. 기록은 JSONL을 직접 써서 넣는다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from server import live as relay  # noqa: E402
from server import on_view  # noqa: E402
from server.app import app as server_app  # noqa: E402

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


def write_log(folder, day, lines):
    with (Path(folder) / f"visits-{day}.jsonl").open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def row(t, event, **fields):
    return {"visit_id": "v1", "t": t, "source_kind": "team_rehearsal", "event": event, **fields}


on_view.OFF.clear()

print("\n1. 작품 목록과 켜짐·꺼짐을 돌려준다")
with TestClient(server_app) as client:
    got = client.get("/api/ops/artworks")
    body = got.json()
    check("200으로 답한다", got.status_code == 200, str(got.status_code))
    check("작품 11점을 준다", len(body["artworks"]) == 11, str(len(body["artworks"])))
    check("기본은 전부 켜짐", all(a["on_view"] for a in body["artworks"]))
    check("꺼진 목록은 비어 있다", body["off"] == [], str(body["off"]))
    check("재시작하면 초기화된다고 알린다", "LIVE_OFF_ARTWORKS" in body["note"], body["note"][:40])
    check("제목을 함께 준다", all(a["title_en"] for a in body["artworks"]))

print("\n2. 기록을 집계해 작품 제목과 켜짐·꺼짐을 붙여 준다")
with tempfile.TemporaryDirectory() as tmp:
    saved = os.environ.get("LIVE_VISIT_DIR")
    os.environ["LIVE_VISIT_DIR"] = tmp
    write_log(tmp, "20261119", [
        row(0.0, "visit_start", start_bucket="2026-11-19T10:00", season_id="", gallery="",
            ui_lang="en", mode="handsfree", model="m", voice="Kore"),
        row(10.0, "artwork_identified", artwork_id=ARTWORK, via="function"),
        row(20.0, "question", artwork_id=ARTWORK, channel="voice", label="artist",
            outcome="answered", first_audio_ms=1700),
        row(60.0, "visit_end", reason="visit_ended", duration_s=60, counts={"question": 1}),
    ])
    try:
        with TestClient(server_app) as client:
            body = client.get("/api/ops/stats?from_day=2026-11-19&to_day=2026-11-19").json()
            check("관람 한 건을 센다", body["visits"]["total"] == 1, str(body["visits"]))
            found = next((a for a in body["artworks"] if a["artwork_id"] == ARTWORK), None)
            check("그 작품이 집계에 들어간다", found is not None and found["questions"] == 1,
                  str(found and found["questions"]))
            check("작품 제목을 붙여 준다", bool(found and found["title_en"]),
                  str(found and found["title_en"])[:40])
            check("켜짐·꺼짐을 붙여 준다", found is not None and found["on_view"] is True)
            check("라벨이 원라벨로 남는다", found is not None and found["labels"]["artist"] == 1,
                  str(found and found["labels"]["artist"]))
            check("기록이 없는 작품을 따로 알린다",
                  len(body["artworks_without_records"]) == 10
                  and ARTWORK not in body["artworks_without_records"],
                  str(len(body["artworks_without_records"])))
            check("읽은 파일을 알려 준다", body["range"]["files"] == ["visits-20261119.jsonl"],
                  str(body["range"]["files"]))
            check("기간을 비우면 오늘 하루를 본다",
                  client.get("/api/ops/stats").status_code == 200)
    finally:
        if saved is None:
            os.environ.pop("LIVE_VISIT_DIR", None)
        else:
            os.environ["LIVE_VISIT_DIR"] = saved

print("\n3. 잘못된 입력은 400으로 거부한다")
with TestClient(server_app) as client:
    for name, query in (("날짜 형식이 틀리면 거부한다", "from_day=11/19&to_day=11/19"),
                        ("기간이 거꾸로면 거부한다", "from_day=2026-11-19&to_day=2026-11-18"),
                        ("모르는 자료 종류는 거부한다", "source_kind=visitors")):
        got = client.get(f"/api/ops/stats?{query}")
        check(name, got.status_code == 400, f"{got.status_code} {got.json().get('detail','')[:40]}")

print("\n4. 작품을 끄고 켠다")
with TestClient(server_app) as client:
    got = client.post(f"/api/ops/artworks/{ARTWORK}/on_view", json={"on_view": False})
    body = got.json()
    check("200으로 답한다", got.status_code == 200, str(got.status_code))
    check("바뀌었다고 알린다", body["changed"] is True, str(body["changed"]))
    check("꺼진 목록에 들어간다", body["off"] == [ARTWORK], str(body["off"]))
    check("같은 응답에 목록을 함께 준다",
          next(a for a in body["artworks"] if a["artwork_id"] == ARTWORK)["on_view"] is False)

    again = client.post(f"/api/ops/artworks/{ARTWORK}/on_view", json={"on_view": False}).json()
    check("같은 값을 또 보내면 바뀌지 않았다고 알린다", again["changed"] is False, str(again["changed"]))

    missing = client.post("/api/ops/artworks/NOPE/on_view", json={"on_view": False})
    check("모르는 작품은 404", missing.status_code == 404, str(missing.status_code))
    check("오류 메시지는 영문 소문자", missing.json()["detail"] == "artwork not found",
          missing.json()["detail"])

print("\n5. 끈 작품이 인식 후보에서 빠지고 모듈 수준 목록은 그대로다")
check("꺼진 작품은 보이지 않는다", ARTWORK not in on_view.visible(relay.artworks))
check("relay.artworks는 11점 그대로다", len(relay.artworks) == 11, str(len(relay.artworks)))
check("relay.comparisons는 20쌍 그대로다", len(relay.comparisons) == 20, str(len(relay.comparisons)))

with TestClient(server_app) as client:
    back = client.post(f"/api/ops/artworks/{ARTWORK}/on_view", json={"on_view": True}).json()
    check("다시 켜면 꺼진 목록이 빈다", back["off"] == [], str(back["off"]))

on_view.OFF.clear()   # 다른 시험을 오염시키지 않는다
print(f"\n운영 API 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
