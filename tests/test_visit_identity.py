"""관람 하나가 기록 하나로 남는지 본다 (server/live.py).

담당: FE1. 11/19 실측에서 관람 2건이 47건으로 집계됐다. 폰이 다시 붙을 때마다 기록이
새로 시작됐기 때문이다. 그러면 운영 페이지의 모든 비율이 분모부터 틀린다.

pytest로는 수집되지 않는다. 이렇게 돌린다:
    PYTHONPATH=. uv run python tests/test_visit_identity.py

Gemini를 부르지 않는다. `visit_log.start()`가 Gemini에 붙기 전에 불리므로 WebSocket을
열고 바로 닫기만 하면 기록이 남는다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tests.sandbox  # noqa: F401  실제 기록 폴더에 쓰지 않게 막는다

from fastapi.testclient import TestClient  # noqa: E402

from server.live import live  # noqa: E402
from server.app import app as server_app  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  통과 · {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  실패 · {name}" + (f" — {detail}" if detail else ""))


def attach(client, session_id, resume):
    """폰이 한 번 붙었다 끊기는 것을 흉내낸다. Gemini 연결은 실패해도 된다."""
    first = {"mode": "handsfree", "session_id": session_id, "profile": {"country": "france"}}
    if resume:
        first["resume"] = True
    try:
        with client.websocket_connect("/ws/live") as ws:
            ws.send_text(json.dumps(first))
            ws.close()
    except Exception:
        pass


def lines(folder):
    out = []
    for path in sorted(Path(folder).glob("visits-*.jsonl")):
        out += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


print("\n1. 같은 관람에 폰이 세 번 붙으면 기록은 하나로 남는다")
with tempfile.TemporaryDirectory() as tmp:
    saved = {k: os.environ.get(k) for k in ("LIVE_VISIT_LOG", "LIVE_VISIT_DIR", "LIVE_VISIT_SOURCE_KIND")}
    os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp, LIVE_VISIT_SOURCE_KIND="team_rehearsal")
    try:
        with TestClient(server_app) as client:
            session_id = client.post("/api/session", json={"profile": {}}).json()["session_id"]
            attach(client, session_id, resume=False)
            attach(client, session_id, resume=True)
            attach(client, session_id, resume=True)
        rows = lines(tmp)
        starts = [r for r in rows if r["event"] == "visit_start"]
        ids = {r["visit_id"] for r in rows}
        check("visit_start가 한 번만 남는다", len(starts) == 1, f"{len(starts)}번")
        check("visit_id가 하나다", len(ids) == 1, f"{len(ids)}개")
        check("관람이 아직 끝나지 않았으므로 visit_end가 없다",
              sum(1 for r in rows if r["event"] == "visit_end") == 0,
              str(sum(1 for r in rows if r['event'] == 'visit_end')))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

print("\n2. 서로 다른 관람은 서로 다른 기록으로 남는다")
with tempfile.TemporaryDirectory() as tmp:
    saved = {k: os.environ.get(k) for k in ("LIVE_VISIT_LOG", "LIVE_VISIT_DIR", "LIVE_VISIT_SOURCE_KIND")}
    os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp, LIVE_VISIT_SOURCE_KIND="team_rehearsal")
    try:
        with TestClient(server_app) as client:
            one = client.post("/api/session", json={"profile": {}}).json()["session_id"]
            two = client.post("/api/session", json={"profile": {}}).json()["session_id"]
            attach(client, one, resume=False)
            attach(client, two, resume=False)
        rows = lines(tmp)
        check("visit_start가 두 번 남는다",
              sum(1 for r in rows if r["event"] == "visit_start") == 2,
              str(sum(1 for r in rows if r['event'] == 'visit_start')))
        check("visit_id가 둘이다", len({r["visit_id"] for r in rows}) == 2,
              str(len({r['visit_id'] for r in rows})))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

print("\n3. 관람을 끝내면 기록이 닫히고, 같은 session_id로 다시 붙으면 새 관람이다")
with tempfile.TemporaryDirectory() as tmp:
    saved = {k: os.environ.get(k) for k in ("LIVE_VISIT_LOG", "LIVE_VISIT_DIR", "LIVE_VISIT_SOURCE_KIND")}
    os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_DIR=tmp, LIVE_VISIT_SOURCE_KIND="team_rehearsal")
    try:
        with TestClient(server_app) as client:
            session_id = client.post("/api/session", json={"profile": {}}).json()["session_id"]
            attach(client, session_id, resume=False)
            client.post(f"/api/session/{session_id}/end")
            # 앞 장들이 끝내지 않은 관람은 저장소에 남아 있으므로 이 관람만 본다.
            check("관람을 끝내면 기록 저장소에서 빠진다", session_id not in live.visit_logs,
                  str(sorted(live.visit_logs)[:1]))
            attach(client, session_id, resume=True)
        rows = lines(tmp)
        ends = [r for r in rows if r["event"] == "visit_end"]
        check("끝낸 관람은 visit_end 하나로 닫힌다", len(ends) == 1, f"{len(ends)}번")
        check("끝낸 이유가 남는다", len(ends) == 1 and ends[0]["reason"] == "visit_ended", str(ends))
        check("그 뒤 다시 붙으면 새 관람으로 센다",
              sum(1 for r in rows if r["event"] == "visit_start") == 2
              and len({r["visit_id"] for r in rows}) == 2,
              f"{sum(1 for r in rows if r['event'] == 'visit_start')}번, "
              f"{len({r['visit_id'] for r in rows})}개")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

print(f"\n관람 식별 시험: 통과 {PASS}건, 실패 {FAIL}건")
if FAIL:
    sys.exit(1)
