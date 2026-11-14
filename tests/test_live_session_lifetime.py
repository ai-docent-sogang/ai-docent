"""Live 중계의 세션 수명 처리 시험. Gemini를 가짜로 바꿔 10분·15분을 기다리지 않고 확인한다.

담당: FE1
같이 보는 파일: tools/live_relay_spike.py (시험 대상), tools/fake_browser_live.py (실제 Gemini로 하는 확인)

왜 가짜로 하는가:
    연결 수명은 약 10분, 음성 전용 세션은 압축이 없으면 15분이다. 실제로 기다리면 한 번
    확인하는 데 10분 넘게 걸리고, GoAway가 언제 오는지는 우리가 정할 수 없다. 그래서 Gemini
    자리에 대본대로 움직이는 가짜를 놓고, 중계가 그 상황에서 무엇을 하는지만 본다.

여기서 확인하지 못하는 것(실제 Gemini·실기기로만 확인된다):
    - 컨텍스트 압축이 실제로 15분 제한을 없애는지, 압축 뒤에도 앞 대화를 기억하는지
    - 재개 핸들로 다시 붙은 뒤 실제로 대화가 이어지는지
    - 실제 GoAway가 연결 종료 몇 초 전에 오는지

실행: PYTHONPATH=. uv run python tests/test_live_session_lifetime.py
"""
import asyncio
import json
import sys
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.genai.errors import APIError

import tools.live_relay_spike as relay

ARTWORK = "KHD_SSIREUM"
CLOSED_1008 = APIError(1008, {"error": {"code": 1008, "message": "Session closed due to client inactivity"}})


# ── Gemini 자리에 놓는 가짜 ───────────────────────────────────────────────
def msg(*, handle=None, resumable=None, go_away=None, audio=None, said=None,
        heard=None, turn_complete=False):
    """중계가 보는 모양만 맞춘 서버 메시지 한 개."""
    content = None
    if audio or said or heard or turn_complete:
        content = SimpleNamespace(
            input_transcription=SimpleNamespace(text=heard) if heard else None,
            output_transcription=SimpleNamespace(text=said) if said else None,
            model_turn=SimpleNamespace(parts=[SimpleNamespace(
                inline_data=SimpleNamespace(data=audio))]) if audio else None,
            turn_complete=turn_complete,
        )
    return SimpleNamespace(
        session_resumption_update=(
            SimpleNamespace(new_handle=handle, resumable=resumable, last_consumed_client_message_index=None)
            if handle is not None else None),
        go_away=SimpleNamespace(time_left="4s") if go_away else None,
        server_content=content,
    )


class FakeSession:
    """대본대로 메시지를 내보내는 가짜 Live 세션. receive()를 부를 때마다 한 턴을 내보낸다."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent = []

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def receive(self):
        if not self.turns:
            # 대본이 끝났다. 실제 Gemini도 조용히 있다가 비활성으로 닫는다.
            await asyncio.sleep(3600)
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        for m in turn:
            await asyncio.sleep(0)
            yield m


class FakeClient:
    """connect()를 부를 때마다 대본의 다음 연결을 내준다. 받은 핸들을 기록한다."""

    def __init__(self, connections):
        self.connections = list(connections)
        self.handles = []      # 연결할 때마다 쓴 재개 핸들
        self.compression = []  # 연결할 때마다 쓴 컨텍스트 압축 설정
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=self._connect))

    def _connect(self, *, model, config):
        self.handles.append(config.session_resumption.handle if config.session_resumption else None)
        self.compression.append(config.context_window_compression)
        nxt = self.connections.pop(0) if self.connections else []
        client = self

        class Ctx:
            async def __aenter__(self):
                if isinstance(nxt, BaseException):
                    raise nxt
                client.session = FakeSession(nxt)
                return client.session

            async def __aexit__(self, *a):
                return False
        return Ctx()


def run(connections, expect, timeout=10):
    """가짜 Gemini를 끼운 중계에 폰처럼 붙어 메시지 expect개를 받는다. (받은 것, 가짜 클라이언트).

    받는 일을 별도 실 에서 한다. 중계는 관람객이 있는 동안 끝나지 않으므로, 볼 것을 다 받으면
    우리가 연결을 닫는다.
    """
    fake = FakeClient(connections)
    relay.make_client = lambda: fake
    got = []
    done = threading.Event()

    with TestClient(relay.app) as c:
        with c.websocket_connect("/ws/live") as ws:
            ws.send_text(json.dumps({"artwork_id": ARTWORK}))

            def reader():
                try:
                    while len(got) < expect:
                        m = ws.receive()
                        if m.get("text"):
                            got.append(json.loads(m["text"]))
                        elif m.get("bytes") is not None:
                            got.append(("bytes", m["bytes"]))
                        elif m.get("type") == "websocket.close":
                            break
                except Exception:
                    pass
                finally:
                    done.set()

            threading.Thread(target=reader, daemon=True).start()
            if not done.wait(timeout):
                print(f"  (경고: {timeout}초 안에 {expect}개를 못 받았다. 받은 것 {len(got)}개)")
            ws.close()
    return got, fake


def types_of(got):
    return [g["type"] if isinstance(g, dict) else g[0] for g in got]


def check(name, cond, detail=""):
    print(f"  {'통과' if cond else '실패'} · {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(name)


failures = []

# ── 1. 비어 있는 동안 GoAway가 오면 우리가 먼저 연결을 옮긴다 ──────────────
print("1. 연결 수명 예고(GoAway) · 답변 중이 아닐 때")
got, fake = run([
    [[msg(handle="h1")], [msg(go_away=True)]],   # 첫 연결: 핸들을 주고 나서 종료 예고
    [[msg(heard="ok", turn_complete=True)]],     # 둘째 연결: 정상
], expect=5)   # ready, reconnecting, reconnected, heard, turn_complete
t = types_of(got)
check("폰 연결은 끊지 않고 reconnecting → reconnected 를 보낸다",
      "reconnecting" in t and "reconnected" in t, str(t))
check("예고를 받은 뒤 받아 둔 핸들로 다시 붙는다", fake.handles[:2] == [None, "h1"], str(fake.handles))
check("압축을 켜고 붙는다(음성 전용 15분 제한 해제)",
      all(c is not None and c.sliding_window is not None for c in fake.compression))
rec = next(g for g in got if g["type"] == "reconnecting")
check("대화가 유지됨을 폰에 알린다", rec.get("kept_conversation") is True, str(rec))

# ── 2. 답변 도중에 GoAway가 오면 그 답을 끝까지 내보낸 뒤 옮긴다 ───────────
print("2. 연결 수명 예고 · 답변 도중일 때")
got, fake = run([
    [[msg(handle="h2")],
     [msg(audio=b"\x01\x02"), msg(go_away=True), msg(audio=b"\x03\x04"),
      msg(said="rest of answer"), msg(turn_complete=True)]],
    [[]],
], expect=7)   # ready, 음성 2개, said, turn_complete, reconnecting, reconnected
t = types_of(got)
audio = [g for g in got if not isinstance(g, dict)]
check("예고 뒤에 온 답변 음성도 폰에 보낸다", len(audio) == 2, f"음성 조각 {len(audio)}개")
check("답을 끊지 않고 turn_complete 까지 보낸 뒤 옮긴다",
      t.index("turn_complete") < t.index("reconnecting"), str(t))
check("turn_complete 는 한 번만 보낸다", t.count("turn_complete") == 1, str(t))

# ── 3. 답변 도중에 연결이 그냥 끊기면 턴을 닫아 버튼을 풀어 준다 ───────────
print("3. 답변 도중 연결이 끊김(폰 버튼이 잠긴 채 남지 않아야 한다)")
got, fake = run([
    [[msg(handle="h3")], [msg(audio=b"\x01"), msg(said="half an ans")], CLOSED_1008],
    [[]],
], expect=6)   # ready, 음성, said, turn_complete, reconnecting, reconnected
t = types_of(got)
check("폰이 기다리지 않도록 turn_complete 를 보낸다", "turn_complete" in t, str(t))
check("그 뒤 재연결을 알린다", t.index("turn_complete") < t.index("reconnecting"), str(t))
check("핸들로 대화를 이어 붙는다", fake.handles[:2] == [None, "h3"], str(fake.handles))

# ── 4. 비활성 종료(1008)에서 다시 붙는다 ──────────────────────────────────
print("4. 질문 사이 2분 비활성으로 Gemini가 닫음(1008)")
got, fake = run([
    [[msg(handle="h4", resumable=True)], CLOSED_1008],
    [[msg(said="ok", turn_complete=True)]],
], expect=5)   # ready, reconnecting, reconnected, said, turn_complete
t = types_of(got)
check("폰 연결을 끊지 않고 다시 붙는다", "reconnected" in t, str(t))
check("받아 둔 핸들을 쓴다", fake.handles[:2] == [None, "h4"], str(fake.handles))

# ── 5. 핸들이 거듭 거부되면 버리고 새 대화로 살린다 ───────────────────────
print("5. 재개 핸들이 거부됨(종료 뒤 2시간 지난 경우 등)")
rejected = APIError(400, {"error": {"code": 400, "message": "invalid session resumption handle"}})
got, fake = run([
    [[msg(handle="h5")], CLOSED_1008],     # 연달아 실패 1 (핸들 없이 붙은 연결)
    rejected, rejected,                    # 연달아 실패 2·3 — 둘 다 핸들로 붙으려다 거부됨
    [[msg(said="새 대화", turn_complete=True)]],
], expect=7)   # ready, reconnecting 3개, reconnected, said, turn_complete
check(f"연달아 {relay.HANDLE_GIVE_UP}번 실패하면 핸들을 버리고 새로 붙는다",
      fake.handles[1:3] == ["h5", "h5"] and fake.handles[3] is None, str(fake.handles))
lost = [g for g in got if g["type"] == "reconnecting" and g.get("kept_conversation") is False]
check("대화를 잃었음을 폰에 알린다", len(lost) == 1, str(types_of(got)))
check("도슨트는 계속 쓸 수 있다(reconnected 가 온다)", "reconnected" in types_of(got))

# ── 6. 되돌릴 수 없는 업데이트로 멀쩡한 핸들을 덮지 않는다 ─────────────────
print("6. resumable 이 꺼진 업데이트는 핸들로 저장하지 않는다")
got, fake = run([
    [[msg(handle="good", resumable=True)], [msg(handle="stale", resumable=False)], CLOSED_1008],
    [[]],
], expect=3)   # ready, reconnecting, reconnected
check("쓸 수 있는 핸들만 남긴다", fake.handles[1] == "good", str(fake.handles))

print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("세션 수명 시험 전부 통과")
