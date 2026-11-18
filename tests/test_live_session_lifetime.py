"""Live 중계의 세션 수명 처리 시험. Gemini를 가짜로 바꿔 10분·15분을 기다리지 않고 확인한다.

담당: FE1
같이 보는 파일: server/live.py (시험 대상), tools/fake_browser_live.py (실제 Gemini로 하는 확인)

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
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.genai.errors import APIError

import server.live as relay
import server.session as sessions
from server import live_config as settings
from server.app import app as server_app
from server.live_conversation import ranked_comparison_ids
from server.live_transcript import clean_said, comparison_in_transcript

verified_comparisons = {
    c["comparison_id"]: c for c in relay.comparisons
    if c.get("verification_status", "").strip().lower() == "verified"}

ARTWORK = "KHD_SSIREUM"
CLOSED_1008 = APIError(1008, {"error": {"code": 1008, "message": "Session closed due to client inactivity"}})


# ── Gemini 자리에 놓는 가짜 ───────────────────────────────────────────────
def msg(*, handle=None, resumable=None, go_away=None, audio=None, said=None,
        heard=None, turn_complete=False, interrupted=False, calls=None, usage=None):
    """중계가 보는 모양만 맞춘 서버 메시지 한 개. calls는 [(이름, 인자), ...] 함수 호출."""
    content = None
    if audio or said or heard or turn_complete or interrupted:
        content = SimpleNamespace(
            interrupted=interrupted or None,
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
        tool_call=SimpleNamespace(function_calls=[
            SimpleNamespace(id=f"call-{i}", name=name, args=args) for i, (name, args) in enumerate(calls)
        ]) if calls else None,
        usage_metadata=usage,
    )


class WaitClientContent:
    """send_client_content가 count번 불린 뒤에야 내보내는 턴."""

    def __init__(self, count, messages):
        self.count, self.messages = count, messages


class Delay:
    """seconds초 뒤에 내보내는 턴(폰이 보낸 것이 서버에 먼저 닿게 할 때)."""

    def __init__(self, seconds, messages):
        self.seconds, self.messages = seconds, messages


class FakeSession:
    """대본대로 메시지를 내보내는 가짜 Live 세션. receive()를 부를 때마다 한 턴을 내보낸다."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent = []            # send_realtime_input으로 받은 것
        self.client_content = []  # send_client_content로 받은 것(글 질문, 인사 신호)
        self.tool_responses = []  # send_tool_response로 받은 함수 결과
        self.order = []           # 받은 순서("realtime" / "client") — 둘을 섞어 보내지 않는지 본다

    async def send_realtime_input(self, **kw):
        self.order.append("realtime")
        self.sent.append(kw)

    async def send_client_content(self, **kw):
        self.order.append("client")
        self.client_content.append(kw)

    async def send_tool_response(self, *, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if not self.turns:
            # 대본이 끝났다. 실제 Gemini도 조용히 있다가 비활성으로 닫는다.
            await asyncio.sleep(3600)
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        if isinstance(turn, Delay):
            await asyncio.sleep(turn.seconds)
            turn = turn.messages
        if isinstance(turn, WaitClientContent):
            # 폰이 글을 보낼 때까지 이 턴을 내보내지 않는다(실제 Gemini도 질문을 받고서 답한다).
            while len(self.client_content) < turn.count:
                await asyncio.sleep(0.01)
            turn = turn.messages
        for m in turn:
            await asyncio.sleep(0)
            yield m


class FakeClient:
    """connect()를 부를 때마다 대본의 다음 연결을 내준다. 받은 핸들을 기록한다."""

    def __init__(self, connections):
        self.connections = list(connections)
        self.handles = []      # 연결할 때마다 쓴 재개 핸들
        self.compression = []  # 연결할 때마다 쓴 컨텍스트 압축 설정
        self.instructions = []  # 연결할 때마다 넣은 시스템 지시문
        self.configs = []      # 연결할 때마다 쓴 설정 전체
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=self._connect))

    def _connect(self, *, model, config):
        self.handles.append(config.session_resumption.handle if config.session_resumption else None)
        self.compression.append(config.context_window_compression)
        self.instructions.append(config.system_instruction)
        self.configs.append(config)
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


def run(connections, expect, timeout=10, profile=None, first=None, after_ready=(), linger=0.0):
    """가짜 Gemini를 끼운 중계에 폰처럼 붙어 메시지 expect개를 받는다. (받은 것, 가짜 클라이언트).

    first: 첫 메시지(없으면 push 모드로 작품 하나). after_ready: ready를 받은 뒤 폰이 보낼 것
    (텍스트는 dict, 바이너리는 bytes). linger: 다 받은 뒤 닫기 전에 기다리는 시간(보낸 것이 처리되게).

    받는 일을 별도 실 에서 한다. 중계는 관람객이 있는 동안 끝나지 않으므로, 볼 것을 다 받으면
    우리가 연결을 닫는다.
    """
    fake = FakeClient(connections)
    relay.make_client = lambda: fake
    got = []
    done = threading.Event()

    with TestClient(server_app) as c:
        with c.websocket_connect("/ws/live") as ws:
            first = dict(first) if first is not None else {"artwork_id": ARTWORK}
            if profile is not None:
                first["profile"] = profile
            ws.send_text(json.dumps(first))

            def reader():
                try:
                    while len(got) < expect:
                        m = ws.receive()
                        if m.get("text"):
                            got.append(json.loads(m["text"]))
                            if got[-1].get("type") == "ready":
                                for out in after_ready:
                                    if isinstance(out, bytes):
                                        ws.send_bytes(out)
                                    else:
                                        ws.send_text(json.dumps(out))
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
            if linger:
                time.sleep(linger)
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

# ── 7. 턴이 끝나면 관람 기억에 남는다 (11/17에 더한 것) ────────────────────
# 이전 중계는 server/session.py를 전혀 쓰지 않아 관람 기억이 쌓이지 않았고, 폰의 관람 요약
# 화면(본 작품 수)이 비어 있었다. BE1 파일을 고치지 않고 record_turn을 부르는 것으로 해결했다.
print("7. 관람 기억 기록")
got, fake = run([
    [[msg(heard="Who painted this?", said="Kim Hong-do painted it.", turn_complete=True)]],
], expect=4)   # ready, heard, said, turn_complete
ready = next(g for g in got if g["type"] == "ready")
visit = sessions.get_session(ready.get("session_id", ""))
check("ready에 이어 쓸 관람 세션 ID가 온다", visit is not None, str(ready.get("session_id")))
check("본 작품으로 기록된다", visit is not None and visit.seen_artwork_ids == [ARTWORK],
      str(visit.seen_artwork_ids if visit else None))
check("질문과 답이 대화 기록에 남는다",
      visit is not None and visit.history
      and visit.history[-1]["visitor"] == "Who painted this?"
      and visit.history[-1]["docent"] == "Kim Hong-do painted it.",
      str(visit.history[-1] if visit and visit.history else None))
# 음성으로 답하므로 어떤 비교를 썼는지 알 수 없다. 추측해서 채우지 않는다(server/live.py 머리말).
check("쓰지 않은 비교쌍을 기록하지 않는다",
      visit is not None and visit.used_comparison_ids == [],
      str(visit.used_comparison_ids if visit else None))

# ── 8. 지시문에 작품·프로필·비교 후보가 들어간다 ───────────────────────────
# 이전에는 ASK_INSTRUCTION(작품 한 점, 비교 없음)을 써서 "외국 작품과 비교"가 빠져 있었다.
print("8. 시스템 지시문 (BE1 build_live_instruction)")
got, fake = run([
    [[msg(heard="hi", turn_complete=True)]],
], expect=3, profile={"country": "France", "age_group": "adult", "language": "en"})
instruction = fake.instructions[0] or ""
check("작품 사실이 들어간다", "FACTS (the only facts you may use)" in instruction)
check("프로필이 들어간다", "VISITOR PROFILE" in instruction and "France" in instruction)
check("비교 후보 칸이 들어간다", "COMPARISON OPTIONS" in instruction)
check("요청-응답용 규칙을 쓰지 않는다", "Do not greet or welcome the visitor" not in instruction)

# ── 9. 목소리 설정 (11/18 추가) ────────────────────────────────────────────
print("9. 목소리(LIVE_VOICE, 없으면 Kore)")
got, fake = run([[[msg(heard="hi", turn_complete=True)]]], expect=3)
voice = fake.configs[0].speech_config.voice_config.prebuilt_voice_config.voice_name
check("push 모드 설정에 목소리가 들어간다", voice == settings.LIVE_VOICE, str(voice))
check("ready에 목소리 이름이 온다", got[0].get("voice") == settings.LIVE_VOICE, str(got[0]))
check("push 모드 ready에 mode가 push로 온다", got[0].get("mode") == "push", str(got[0]))
check("push 모드는 먼저 말을 걸지 않는다", fake.session.client_content == [])

# ── 10~13. handsfree 모드 (11/18 추가) ───────────────────────────────────
HANDSFREE = {"mode": "handsfree", "profile": {"country": "France", "age_group": "adult", "language": "en"}}

print("10. handsfree 연결 설정·인사")
got, fake = run([[[msg(said="Hello! Where are you from?", turn_complete=True)]]], expect=3, first=HANDSFREE)
cfg = fake.configs[0]
aad = cfg.realtime_input_config.automatic_activity_detection
check("작품 없이도 연결된다(ready)", got[0].get("type") == "ready" and got[0].get("mode") == "handsfree", str(got[0]))
check("자동 음성 감지를 켠다", aad is not None and aad.disabled is False, str(aad))
names = [f.name for t in cfg.tools for f in t.function_declarations]
check("함수 두 개를 선언한다", names == ["report_current_artwork", "report_comparison"], str(names))
enum = cfg.tools[0].function_declarations[0].parameters.properties["artwork_id"].enum
check("작품 함수 값은 11개 ID + unknown", len(enum) == 12 and "unknown" in enum and ARTWORK in enum, str(enum))
check("압축·재개 설정을 그대로 쓴다(영상이 섞이면 압축 없이 2분)",
      cfg.context_window_compression is not None and cfg.session_resumption is not None)
check("같은 목소리를 쓴다", cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == settings.LIVE_VOICE)
hf_instruction = fake.instructions[0]
check("지시문에 BE1 규칙·프로필·11점 후보·함수 규칙이 들어간다",
      "Fact rules" in hf_instruction and "VISITOR PROFILE" in hf_instruction and "France" in hf_instruction
      and "EXHIBITION" in hf_instruction and "report_current_artwork" in hf_instruction, hf_instruction[:80])
check("연결되면 Live가 먼저 인사하게 신호를 보낸다",
      len(fake.session.client_content) == 1
      and settings.GREETING_CUE in fake.session.client_content[0]["turns"].parts[0].text)
greet_visit = sessions.get_session(got[0]["session_id"])
check("인사 신호를 관람객 말로 기록하지 않는다",
      greet_visit.history and greet_visit.history[-1]["visitor"] == "", str(greet_visit.history))

print("11. handsfree 소리·사진·글 전달")
jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
got, fake = run([[[msg(said="hi", turn_complete=True)]]], expect=3, first=HANDSFREE, linger=0.5, after_ready=[
    b"\x00\x00" * 1600,
    {"type": "frame", "jpeg": base64.b64encode(jpeg).decode()},
    {"type": "frame", "jpeg": "%%%not-base64%%%"},
    {"type": "text", "text": "Who painted this?"},
    {"type": "speech_start"},   # push 신호는 handsfree에서 무시한다
])
sent = fake.session.sent
videos = [s["video"] for s in sent if "video" in s]
audios = [s["audio"] for s in sent if "audio" in s]
check("마이크 PCM을 그대로 보낸다(앞뒤 무음을 덧붙이지 않는다)",
      len(audios) == 1 and audios[0].data == b"\x00\x00" * 1600, f"{len(audios)}개")
check("사진은 image/jpeg로 보낸다", len(videos) == 1 and videos[0].data == jpeg
      and videos[0].mime_type == "image/jpeg", str(videos))
check("깨진 사진은 버린다", len(videos) == 1)
check("push 신호(activity_start)를 보내지 않는다", not any("activity_start" in s for s in sent), str(sent))
texts = [c["turns"].parts[0].text for c in fake.session.client_content]
check("글 질문은 send_client_content로 보낸다", texts[1:] == ["Who painted this?"], str(texts))

print("12. handsfree 끼어들기")
got, fake = run([[[msg(audio=b"\x01"), msg(said="The paint"), msg(interrupted=True), msg(turn_complete=True)]]],
                expect=5, first=HANDSFREE)   # ready, 음성, said, interrupted, turn_complete
t = types_of(got)
check("interrupted를 폰에 보낸다", "interrupted" in t, str(t))
check("interrupted 뒤에 turn_complete가 온다", "interrupted" in t and t.index("interrupted") < t.index("turn_complete"), str(t))

print("13. handsfree 함수 호출")
got, fake = run([[
    [msg(calls=[("report_current_artwork", {"artwork_id": ARTWORK})])],
    [msg(calls=[("report_comparison", {"comparison_id": "C_INWANG_CEZANNE"})])],   # 다른 작품의 비교
    [msg(calls=[("report_comparison", {"comparison_id": "C_KHD_BRUEGEL"})])],
    [msg(heard="Can you compare it?"), msg(said="Think of Bruegel's Peasant Wedding."),
     msg(turn_complete=True)],
]], expect=6, first=HANDSFREE, linger=0.3)
# ready, artwork, comparison, heard, said, turn_complete
responses = fake.session.tool_responses
check("함수마다 결과를 돌려준다(id·이름 일치)",
      [(r.id, r.name) for r in responses] == [("call-0", "report_current_artwork"),
                                              ("call-0", "report_comparison"), ("call-0", "report_comparison")],
      str([(r.id, r.name) for r in responses]))
art_result = responses[0].response
check("작품 결과에 확인된 사실이 들어간다", "FACTS (the only facts you may use)" in art_result["artwork"])
check("작품 결과에 비교 후보와 그 ID가 들어간다",
      "COMPARISON OPTIONS" in art_result["comparison_options"]
      # ID를 여기 적어 두지 않는다. 예원님이 비교쌍을 늘리면 이 시험만 깨지고, 깨진 사람은
      # 왜 깨졌는지 알기 어렵다(11/18에 C_KHD_HOKUSAI_MANGA가 ..._SUMO로 바뀌어 실제로 깨졌다).
      and set(art_result["comparison_ids"]) == {
          c["comparison_id"] for c in verified_comparisons.values()
          if c["artwork_id"] == ARTWORK}, str(art_result.get("comparison_ids")))
check("다른 작품의 비교쌍은 거절한다", responses[1].response.get("ok") is False, str(responses[1].response))
check("지금 작품의 검증된 비교쌍은 받는다", responses[2].response.get("ok") is True
      and responses[2].response.get("similarities"), str(responses[2].response)[:120])
arts = [g for g in got if isinstance(g, dict) and g.get("type") == "artwork"]
comps = [g for g in got if isinstance(g, dict) and g.get("type") == "comparison"]
check("폰에 artwork를 보낸다", arts and arts[0]["artwork_id"] == ARTWORK and arts[0]["artwork_title"], str(arts))
check("폰에 comparison은 받은 것 하나만 보낸다",
      [(c["comparison_id"], c["artwork_id"], c["source"]) for c in comps]
      == [("C_KHD_BRUEGEL", ARTWORK, "function")], str(comps))
# 화면이 작품·비교 정보를 베껴 두지 않게 서버가 보여 줄 값을 같이 보낸다(11/18).
# 베낀 목록은 예원님이 CSV를 늘릴 때마다 어긋났다. 빠지면 요약에서 비교가 조용히 사라진다.
pair = verified_comparisons["C_KHD_BRUEGEL"]
check("artwork에 작가를 같이 보낸다(화면이 작품 목록을 베끼지 않게)",
      arts[0].get("artist") == relay.artworks[ARTWORK]["artist"], str(arts[0]))
check("comparison에 외국 작품의 제목·작가·소장처·링크를 같이 보낸다",
      all(comps[0].get(k) == pair[k] for k in
          ("foreign_title", "foreign_artist", "foreign_collection", "foreign_url")), str(comps[0]))
check("비교 설명 재료(angle·유사점·차이점)는 폰에 보내지 않는다",
      not any(k in comps[0] for k in ("angle", "similarities", "differences")), str(comps[0]))
visit = sessions.get_session(got[0]["session_id"])
check("record_turn에 작품과 comparison_id가 들어간다",
      visit.seen_artwork_ids == [ARTWORK] and visit.used_comparison_ids == ["C_KHD_BRUEGEL"],
      f"{visit.seen_artwork_ids} {visit.used_comparison_ids}")
check("대화 기록에 질문과 답이 남는다",
      visit.history[-1] == {"visitor": "Can you compare it?", "docent": "Think of Bruegel's Peasant Wedding."},
      str(visit.history[-1]))

print("14. handsfree unknown 작품")
got, fake = run([[[msg(calls=[("report_current_artwork", {"artwork_id": "unknown"})])],
                  [msg(said="Could you point the camera at the painting?", turn_complete=True)]]],
                expect=3, first=HANDSFREE, linger=0.3)
r = fake.session.tool_responses[0].response
check("unknown이면 사진을 비춰 달라는 지시를 돌려준다", r["artwork_id"] == "unknown" and "camera" in r["instruction"], str(r))
check("unknown이면 artwork를 보내지 않는다", "artwork" not in types_of(got), str(types_of(got)))

print("15. handsfree 글 질문(화면이 말풍선을 직접 그린다)")
# 인사 턴 뒤에 글 질문을 보내고, 가짜 Gemini가 다음 턴(답)을 내보내게 한다.
got, fake = run([[[msg(said="Hello!", turn_complete=True)],
                  WaitClientContent(2, [msg(said="Kim Hong-do painted it.", turn_complete=True)])]],
                expect=5, first=HANDSFREE, linger=0.3,
                after_ready=[{"type": "text", "text": "Who painted this?"}])
t = types_of(got)
check("글 질문에는 heard를 보내지 않는다", "heard" not in t, str(t))
visit = sessions.get_session(got[0]["session_id"])
check("record_turn의 관람객 말에 글 질문 원문이 들어간다",
      any(h == {"visitor": "Who painted this?", "docent": "Kim Hong-do painted it."} for h in visit.history),
      str(visit.history))

# ── 16~20. 폰이 다시 붙을 때(resume, 11/18 오후) ─────────────────────────
print("16. resume: 저장된 핸들로 대화를 잇는다")
visit = sessions.create_session()
SID = visit.session_id
got, fake = run([[[msg(handle="hA")],
                  [msg(calls=[("report_current_artwork", {"artwork_id": ARTWORK})])],
                  [msg(said="Kim Hong-do.", turn_complete=True)]]],
                expect=4, first={"mode": "handsfree", "session_id": SID}, linger=0.3)
check("첫 연결은 resumed를 담지 않는다(새 관람)", "resumed" not in got[0], str(got[0]))
check("폰 WS가 끊겨도 핸들과 작품이 남는다",
      relay.resume_store.get(SID, {}).get("handle") == "hA"
      and relay.resume_store[SID]["artwork_id"] == ARTWORK, str(relay.resume_store.get(SID)))
got, fake = run([[[msg(said="Yes, you asked who painted it.", turn_complete=True)]]],
                expect=3, first={"mode": "handsfree", "session_id": SID, "resume": True})
check("저장된 핸들로 Gemini에 붙는다", fake.handles[0] == "hA", str(fake.handles))
check("ready.resumed=true", got[0].get("type") == "ready" and got[0].get("resumed") is True, str(got[0]))
check("이어 붙으면 인사 신호를 보내지 않는다", fake.session.client_content == [],
      str(fake.session.client_content))
check("같은 관람 세션에 이어 쓴다", got[0]["session_id"] == SID)

print("17. resume: 저장된 핸들이 없으면 새 대화(resumed=false), 인사 대신 돌아왔다고 말한다")
fresh = sessions.create_session()
got, fake = run([[[msg(said="I'm back.", turn_complete=True)]]],
                expect=3, first={"mode": "handsfree", "session_id": fresh.session_id, "resume": True})
cue = fake.session.client_content[0]["turns"].parts[0].text if fake.session.client_content else ""
check("핸들 없이 붙는다", fake.handles[0] is None, str(fake.handles))
check("ready.resumed=false", got[0].get("resumed") is False, str(got[0]))
check("처음 인사가 아니라 다시 연결됐다는 신호를 보낸다",
      cue.startswith(settings.RECONNECT_CUE) and settings.GREETING_CUE not in cue, cue[:80])

print("18. resume: 2시간 지난 핸들은 버리고, 저장된 작품 사실을 넘긴다")
relay.resume_store[SID]["updated"] -= relay.HANDLE_TTL_S + 1
relay.resume_store[SID]["handle"] = "hOld"
got, fake = run([[[msg(said="I'm back.", turn_complete=True)]]],
                expect=3, first={"mode": "handsfree", "session_id": SID, "resume": True})
check("2시간 지난 핸들로 붙지 않는다", fake.handles[0] is None, str(fake.handles))
check("만료된 항목은 저장소에서 지운다", relay.resume_store.get(SID, {}).get("handle") != "hOld",
      str(relay.resume_store.get(SID)))
check("ready.resumed=false", got[0].get("resumed") is False, str(got[0]))
check("만료 뒤에는 작품도 이어받지 않는다(2시간 넘은 관람)",
      "FACTS" not in (fake.session.client_content[0]["turns"].parts[0].text if fake.session.client_content else ""))

print("19. resume: 핸들이 거부되면 기존 연달아 실패 처리로 새 대화")
v = sessions.create_session()
relay.resume_store[v.session_id] = {"handle": "hBad", "artwork_id": ARTWORK, "updated": time.time()}
got, fake = run([rejected, rejected, rejected, [[msg(said="I'm back.", turn_complete=True)]]],
                expect=3, first={"mode": "handsfree", "session_id": v.session_id, "resume": True})
cue = fake.session.client_content[0]["turns"].parts[0].text if fake.session.client_content else ""
check("핸들로 세 번 시도 뒤 핸들 없이 붙는다",
      fake.handles == ["hBad", "hBad", "hBad", None], str(fake.handles))
check("ready 전에는 reconnecting을 보내지 않는다", types_of(got)[0] == "ready", str(types_of(got)))
check("ready.resumed=false", got[0].get("resumed") is False, str(got[0]))
check("저장된 작품의 사실을 넘겨 이어 말하게 한다", ARTWORK in cue and "FACTS" in cue, cue[:120])

print("20. 같은 session_id로 WS가 둘 붙으면 앞의 것을 닫는다")
v = sessions.create_session()
fake = FakeClient([[[msg(said="one", turn_complete=True)]], [[msg(said="two", turn_complete=True)]]])
relay.make_client = lambda: fake
closed = {}
with TestClient(server_app) as c:
    with c.websocket_connect("/ws/live") as ws1:
        ws1.send_text(json.dumps({"mode": "handsfree", "session_id": v.session_id}))
        first1 = json.loads(ws1.receive_text())

        def watch():
            try:
                while True:
                    m = ws1.receive()
                    if m.get("type") == "websocket.close":
                        closed["code"] = m.get("code")
                        return
            except Exception as e:
                closed["exc"] = repr(e)

        th = threading.Thread(target=watch, daemon=True)
        th.start()
        with c.websocket_connect("/ws/live") as ws2:
            ws2.send_text(json.dumps({"mode": "handsfree", "session_id": v.session_id, "resume": True}))
            first2 = json.loads(ws2.receive_text())
            th.join(5)
            ws2.close()
check("둘째 연결은 ready를 받는다", first2.get("type") == "ready", str(first2))
check("앞 연결은 닫힌다", closed.get("code") == 4000 or "exc" in closed, str(closed))
check("지금 연결 목록에서 정리된다", v.session_id not in relay.active_connections)

# ── 21~23. 11/18 실기기 결과로 더한 것 ──────────────────────────────────
def watch_close(first, pings_for=0.0, wait=4.0, script=None):
    """폰처럼 붙고 pings_for초 동안 0.2초마다 ping을 보낸 뒤 입력을 멈춘다. (닫힌 코드, 닫히기까지 초, fake)."""
    fake = FakeClient(script or [[[msg(handle="hZ")]]])
    relay.make_client = lambda: fake
    out = {}
    with TestClient(server_app) as c:
        with c.websocket_connect("/ws/live") as ws:
            ws.send_text(json.dumps(first))
            out["ready"] = json.loads(ws.receive_text())
            started = time.monotonic()

            def pinger():
                while time.monotonic() - started < pings_for:
                    ws.send_text(json.dumps({"type": "ping"}))
                    time.sleep(0.2)

            def watch():
                try:
                    while True:
                        m = ws.receive()
                        if m.get("type") == "websocket.close":
                            out["code"], out["after"] = m.get("code"), time.monotonic() - started
                            return
                except Exception as e:
                    out["exc"] = repr(e)

            threading.Thread(target=pinger, daemon=True).start()
            th = threading.Thread(target=watch, daemon=True)
            th.start()
            th.join(wait)
            if "code" not in out:
                ws.close()
    return out, fake


print("21. 폰이 아무것도 보내지 않으면 죽은 연결로 보고 닫는다(handsfree)")
saved_idle = settings.PHONE_IDLE_S
settings.PHONE_IDLE_S = 0.6
v = sessions.create_session()
out, fake = watch_close({"mode": "handsfree", "session_id": v.session_id})
check("입력이 없으면 닫는다(코드 4001)", out.get("code") == 4001, str(out))
check("정한 시간쯤에 닫는다", 0.5 <= out.get("after", 0) <= 2.0, f"{out.get('after', 0):.2f}초")
check("재개 핸들은 저장소에 남는다", relay.resume_store.get(v.session_id, {}).get("handle") == "hZ",
      str(relay.resume_store.get(v.session_id)))
check("지금 연결 목록에서 정리된다", v.session_id not in relay.active_connections)
out, fake = watch_close({"mode": "handsfree", "session_id": sessions.create_session().session_id}, pings_for=1.5)
check("ping이 오는 동안은 닫지 않고, 멈추면 닫는다",
      out.get("code") == 4001 and out.get("after", 0) >= 1.5, str(out))
check("ping은 Gemini로 보내지 않는다", fake.session.sent == [] and fake.session.client_content[1:] == [],
      str(fake.session.sent)[:100])
out, fake = watch_close({"artwork_id": ARTWORK}, wait=1.5)
check("push 모드는 입력이 없어도 닫지 않는다(버튼 사이에는 보내는 것이 없다)", "code" not in out, str(out))
settings.PHONE_IDLE_S = saved_idle

print("22. 추임새에 답하지 않게: 지시문과 자동 음성 감지 조절점")
got, fake = run([[[msg(said="hi", turn_complete=True)]]], expect=3, first=HANDSFREE)
aad = fake.configs[0].realtime_input_config.automatic_activity_detection
check("기본값: 시작 민감도 LOW, 침묵 700ms, 앞 여유 300ms",
      aad.start_of_speech_sensitivity == relay.types.StartSensitivity.START_SENSITIVITY_LOW
      and aad.silence_duration_ms == 700 and aad.prefix_padding_ms == 300, str(aad))
check("지시문에 추임새·혼잣말에는 침묵하라는 규칙이 있다", "backchannel" in fake.instructions[0])
saved = (settings.LIVE_START_SENSITIVITY, settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS)
settings.LIVE_START_SENSITIVITY, settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS = "HIGH", 550, 200
got, fake = run([[[msg(said="hi", turn_complete=True)]]], expect=3, first=HANDSFREE)
aad = fake.configs[0].realtime_input_config.automatic_activity_detection
check("환경 변수 값이 설정에 들어간다(HIGH, 550, 200)",
      aad.start_of_speech_sensitivity == relay.types.StartSensitivity.START_SENSITIVITY_HIGH
      and aad.silence_duration_ms == 550 and aad.prefix_padding_ms == 200, str(aad))
settings.LIVE_START_SENSITIVITY, settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS = saved

print("23. 사진 정책 on_speech: 인사 턴이 끝난 뒤 1장, 말이 시작될 때 최신 1장")
settings.FRAME_POLICY = "on_speech"
A, B, C = (b"\xff\xd8A", b"\xff\xd8B", b"\xff\xd8C")
got, fake = run([[
    Delay(0.5, [msg(heard="Who painted"), msg(heard=" this?"),
                msg(calls=[("report_current_artwork", {"artwork_id": ARTWORK})])]),
    [msg(said="Kim Hong-do.", turn_complete=True)],
]], expect=6, first=HANDSFREE, linger=0.3, after_ready=[
    {"type": "frame", "jpeg": base64.b64encode(x).decode()} for x in (A, B, C)])
videos = [x["video"].data for x in fake.session.sent if "video" in x]
# 인사 턴 동안에는 사진을 들고만 있는다(26번 참고). 이 대본은 인사 턴이 끝나기 전에 관람객이
# 말을 시작하므로, 그 순간의 최신 사진 C 하나만 넘어간다(앞의 A는 C로 덮인다).
check("인사 턴에는 사진을 넣지 않고, 말이 시작될 때 최신 1장을 넘긴다", videos == [C], str(videos))
check("이 정책에서도 report_current_artwork가 동작한다",
      fake.session.tool_responses and fake.session.tool_responses[0].response.get("artwork_id") == ARTWORK
      and "artwork" in types_of(got), str(types_of(got)))
settings.FRAME_POLICY = "every"

print("24. 답변 받아쓰기의 말 아닌 표시는 폰에 보내지 않는다")
got, fake = run([[[msg(said="<no speech>"), msg(said="{pause}"), msg(said="\u200b"), msg(turn_complete=True)]]],
                expect=2, first=HANDSFREE)
check("표시만 있는 조각은 said로 보내지 않는다", types_of(got) == ["ready", "turn_complete"], str(types_of(got)))
check("정상 문장은 그대로 둔다", clean_said("Look at the shoes.") == "Look at the shoes.")

print("25. 함수 없이 말한 비교를 받아쓰기에서 찾는다")
ART_CALL = msg(calls=[("report_current_artwork", {"artwork_id": ARTWORK})])
got, fake = run([[
    [ART_CALL],
    [msg(heard="Compare it?"), msg(said="Think of Pieter Bruegel's \"Peasant Wedding\"."), msg(turn_complete=True)],
]], expect=6, first=HANDSFREE, linger=0.3)   # ready, artwork, heard, said, comparison, turn_complete
comps = [g for g in got if isinstance(g, dict) and g.get("type") == "comparison"]
visit = sessions.get_session(got[0]["session_id"])
check("함수 없이 제목이 나오면 comparison(source transcript)을 보낸다",
      [(c["comparison_id"], c["artwork_id"], c["source"]) for c in comps]
      == [("C_KHD_BRUEGEL", ARTWORK, "transcript")], str(comps))
check("받아쓰기로 찾은 비교에도 보여 줄 값이 들어간다(함수 경로와 같게)",
      comps[0].get("foreign_title") == verified_comparisons["C_KHD_BRUEGEL"]["foreign_title"],
      str(comps[0]))
check("record_turn에 그 비교가 누적된다", visit.used_comparison_ids == ["C_KHD_BRUEGEL"], str(visit.used_comparison_ids))

got, fake = run([[
    [ART_CALL],
    [msg(calls=[("report_comparison", {"comparison_id": "C_KHD_BRUEGEL"})])],
    [msg(said="Think of Peasant Wedding by Bruegel."), msg(turn_complete=True)],
]], expect=5, first=HANDSFREE, linger=0.3)
comps = [g for g in got if isinstance(g, dict) and g.get("type") == "comparison"]
check("함수가 불린 턴은 받아쓰기로 다시 보내지 않는다",
      [c.get("source") for c in comps] == ["function"], str(comps))

got, fake = run([[
    [ART_CALL],
    [msg(said="Some compare it with Mont Sainte-Victoire by Cezanne or Children's Games by Bruegel."),
     msg(turn_complete=True)],
]], expect=4, first=HANDSFREE, linger=0.3)
check("다른 작품의 비교쌍 제목은 무시한다", "comparison" not in types_of(got), str(types_of(got)))

got, fake = run([[
    [msg(said="This looks like Peasant Wedding."), msg(turn_complete=True)],
]], expect=3, first=HANDSFREE, linger=0.3)
check("지금 작품이 없으면 찾지 않는다", "comparison" not in types_of(got), str(types_of(got)))

got, fake = run([[
    [ART_CALL],
    [msg(said="Peasant Wedding by Bruegel shows a feast."), msg(turn_complete=True)],
    WaitClientContent(3, [msg(said="Back to Peasant Wedding again."), msg(turn_complete=True)]),
]], expect=7, first=HANDSFREE, linger=0.3, after_ready=[{"type": "text", "text": "more?"},
                                                         {"type": "text", "text": "and?"}])
comps = [g for g in got if isinstance(g, dict) and g.get("type") == "comparison"]
check("이미 누적된 비교는 다시 보내지 않는다", len(comps) == 1, str(comps))

got, fake = run([[
    [ART_CALL],
    [msg(said="Hokusai drew a red fuji too."), msg(turn_complete=True)],
]], expect=4, first=HANDSFREE, linger=0.3)
check("다른 작품의 짧은 제목(Red Fuji)도 무시한다", "comparison" not in types_of(got), str(types_of(got)))
check("짧은 제목은 작가 이름이 있어야 인정한다(INWANG에서)",
      comparison_in_transcript("like Red Fuji", "JS_INWANG", verified_comparisons) == ""
      and comparison_in_transcript("Hokusai painted Red Fuji", "JS_INWANG", verified_comparisons) == "C_INWANG_HOKUSAI")

print("26. 인사 턴: 모델 속 글이 자막에 섞여 와도 폰에 보내지 않고 로그에 남긴다")
# 11/18 멘토 전달본에서 본 증상 그대로. 인사를 하다 말고 함수 호출을 글자로 흘린 뒤 다시 인사했다.
#   "…what kind of art do you usually enjoy? -=call:report_current_artwork{artwork_id:unknown"
#   "Welcome to the Joseon painting gallery! …"
# 같은 날 포트 8055에서 실제 Gemini로 돌려 보니 인사 턴마다 모양만 다른 속 글이 따라왔다
# ("---(No function call needed…)---", "=====…"). 말소리에는 없고 받아쓰기 길로만 온다.
LEAK_TURN = [
    msg(audio=b"\x01\x02"),
    msg(said="Welcome to the gallery; where are you from, and what kind of art do you usually enjoy?"),
    msg(said=" -=call:report_current"),          # 조각이 끊겨 온다
    msg(said="_artwork{artwork_id:unknown"),
    msg(said="Welcome to the Joseon painting gallery! I'm so pleased you're here."),
    msg(turn_complete=True),
]


def run_quiet(*a, **kw):
    """서버 로그를 가로채서 돌린다. (받은 것, 가짜 클라이언트, 서버가 찍은 글)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        got, fake = run(*a, **kw)
    return got, fake, buffer.getvalue()


got, fake, log = run_quiet([[LEAK_TURN]], expect=4, first=HANDSFREE, linger=0.3)
said = "".join(g["text"] for g in got if isinstance(g, dict) and g.get("type") == "said")
check("폰 자막에 함수 호출 글자가 가지 않는다",
      "call:" not in said and "report_current_artwork" not in said, repr(said))
check("속 글 앞까지의 인사는 그대로 보낸다",
      said == "Welcome to the gallery; where are you from, and what kind of art do you usually enjoy?",
      repr(said))
leak_line = next((l for l in log.splitlines() if "모델 속 글" in l), "로그에 없다")
check("왜 걸렀는지는 서버 로그에 남는다", "report_current" in leak_line, leak_line)
# 걸러 낸 글의 뒷부분은 도슨트가 관람객에게 한 말이다. 출력을 파일로 넘기면 저장이 되므로
# (AGENTS.md: 음성은 처리에만 쓰고 저장하지 않는다) 길이만 남기고 글자는 남기지 않는다.
check("도슨트가 한 말은 서버 로그에 남지 않는다",
      "Joseon painting gallery" not in log and "pleased you're here" not in log, leak_line)
check("잘라 낸 뒷부분의 길이를 적는다", "뒤에 83자" in leak_line, leak_line)
leak_visit = sessions.get_session(got[0]["session_id"])
check("관람 기억에도 걸러 낸 글이 들어가지 않는다",
      leak_visit.history and "call:" not in leak_visit.history[-1]["docent"], str(leak_visit.history)[-120:])

for mark in ("---\n(No function call needed, per instructions to greet first.)---",
             " =========================================="):
    got, fake, log = run_quiet([[[msg(said="Welcome to the gallery."), msg(said=mark),
                                  msg(turn_complete=True)]]], expect=3, first=HANDSFREE, linger=0.3)
    said = "".join(g["text"] for g in got if isinstance(g, dict) and g.get("type") == "said")
    check(f"가로줄·등호로 시작하는 속 글도 거른다({mark[:6].strip()!r})",
          said == "Welcome to the gallery." and "모델 속 글" in log, repr(said))

got, fake, log = run_quiet([[[msg(said="Kim Hong-do - a court painter - drew it."), msg(said=" Report?"),
                              msg(turn_complete=True)]]], expect=3, first=HANDSFREE, linger=0.3)
said = "".join(g["text"] for g in got if isinstance(g, dict) and g.get("type") == "said")
check("보통 말에 든 붙임표·report 라는 낱말은 그대로 둔다",
      said == "Kim Hong-do - a court painter - drew it. Report?" and "모델 속 글" not in log, repr(said))

print("27. 인사 턴에는 사진을 넣지 않고, 인사 신호를 realtime 입력보다 먼저 보낸다")
HELLO_JPEG = b"\xff\xd8\xff\xe0one"
got, fake = run([[
    WaitClientContent(1, [msg(said="Welcome.")]),       # 인사 신호를 받고서 인사한다
    [msg(said=" Nice to meet you.", turn_complete=True)],
]], expect=4, first=HANDSFREE, linger=0.5, after_ready=[
    {"type": "frame", "jpeg": base64.b64encode(HELLO_JPEG).decode()}])
check("인사 신호를 realtime 입력보다 먼저 보낸다", fake.session.order[:1] == ["client"], str(fake.session.order))
videos = [x["video"].data for x in fake.session.sent if "video" in x]
check("인사 중에 온 사진은 들고 있다가 인사가 끝난 뒤 넘긴다", videos == [HELLO_JPEG], str(videos))

print("28. .env의 오타와 빈 값에 서버가 죽지 않고 기본값으로 켜진다")
# 환경 변수는 server.live를 불러오는 순간 읽는다. 그래서 이 프로세스가 아니라 새 프로세스에서
# 불러 본다. 불러오다 예외가 나면 returncode가 0이 아니고, 그것이 uvicorn이 통째로 죽는 경우다.
ENV_PROBE = ("import json, server.live; from server import live_config as l; print(json.dumps({"
             "'model': l.LIVE_MODEL, 'voice': l.LIVE_VOICE, 'policy': l.FRAME_POLICY,"
             "'start': l.LIVE_START_SENSITIVITY, 'silence': l.LIVE_SILENCE_MS,"
             "'prefix': l.LIVE_PREFIX_MS, 'idle': l.PHONE_IDLE_S}))")
DEFAULTS = {"model": "gemini-3.8-live", "voice": "Kore", "policy": "every",
            "start": "LOW", "silence": 700, "prefix": 300, "idle": 30.0}


def one_line(text):
    return text.replace("\n", " | ")[-160:]


def load_live_with(**env):
    """환경 변수를 바꾼 새 프로세스에서 server.live를 불러온다. 돌려주는 값: (출력, 설정 또는 None)."""
    done = subprocess.run([sys.executable, "-c", ENV_PROBE], capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": ".", **env})
    out = done.stdout + done.stderr
    return out, (json.loads(done.stdout.splitlines()[-1]) if done.returncode == 0 else None)


out, got = load_live_with(LIVE_PHONE_IDLE_S="30s", LIVE_SILENCE_MS="칠백", LIVE_PREFIX_MS="0.3s",
                          LIVE_START_SENSITIVITY="MEDIUM", LIVE_FRAME_POLICY="sometimes")
check("오타가 있어도 불러오다 죽지 않고 전부 기본값이 된다", got == DEFAULTS, one_line(out))
check("고친 값마다 경고 한 줄을 찍는다",
      all(f"[live] {name}" in out for name in
          ("LIVE_PHONE_IDLE_S", "LIVE_SILENCE_MS", "LIVE_PREFIX_MS",
           "LIVE_START_SENSITIVITY", "LIVE_FRAME_POLICY")), one_line(out))

out, got = load_live_with(LIVE_MODEL="", LIVE_VOICE="", LIVE_FRAME_POLICY="",
                          LIVE_START_SENSITIVITY="", LIVE_SILENCE_MS="", LIVE_PREFIX_MS="",
                          LIVE_PHONE_IDLE_S="")
check("이름만 쓰고 비워 둔 줄도 기본값이 된다(빈 모델 이름으로 켜지지 않는다)", got == DEFAULTS, one_line(out))

out, got = load_live_with(LIVE_MODEL="gemini-3.8-live-preview", LIVE_VOICE="Puck",
                          LIVE_FRAME_POLICY="on_speech", LIVE_START_SENSITIVITY="high",
                          LIVE_SILENCE_MS="550", LIVE_PREFIX_MS="200", LIVE_PHONE_IDLE_S="45.5")
check("제대로 쓴 값은 그대로 들어간다",
      got == {"model": "gemini-3.8-live-preview", "voice": "Puck", "policy": "on_speech",
              "start": "HIGH", "silence": 550, "prefix": 200, "idle": 45.5}, str(got))

saved_config = (settings.LIVE_MODEL, settings.LIVE_VOICE, settings.FRAME_POLICY,
                settings.LIVE_START_SENSITIVITY, settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS,
                settings.PHONE_IDLE_S)
(settings.LIVE_MODEL, settings.LIVE_VOICE, settings.FRAME_POLICY, settings.LIVE_START_SENSITIVITY,
 settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS, settings.PHONE_IDLE_S) = (
    "gemini-3.8-live", "Kore", "every", "LOW", 700, 300, 30.0)
check("켤 때 찍는 한 줄에 지금 값이 다 들어간다",
      settings.env_summary_line() == "[live] model=gemini-3.8-live voice=Kore frame_policy=every "
      "start=LOW silence=700ms prefix=300ms idle=30s", settings.env_summary_line())
(settings.LIVE_MODEL, settings.LIVE_VOICE, settings.FRAME_POLICY, settings.LIVE_START_SENSITIVITY,
 settings.LIVE_SILENCE_MS, settings.LIVE_PREFIX_MS, settings.PHONE_IDLE_S) = saved_config

# ── 29. 관람 기록 (11/18 저녁) ────────────────────────────────────────────
# ── 30. 비교 후보 글의 순서와 ID 목록의 순서가 같아야 한다 ──────────────────
print("30. 비교 후보 글 순서와 ID 순서가 어긋나지 않는다")
import re as _re  # noqa: E402

from server.live_context import comparison_block as _block  # noqa: E402

for _profile in ({"country": "japan"}, {"region": "japan"}, {"country": "france"},
                 {"region": "france"}, {}):
    _text = _block(relay.comparisons, ARTWORK, _profile, ())
    _ids = ranked_comparison_ids(ARTWORK, _profile, (), verified_comparisons)
    # BE1의 글은 "1. <제목> by <작가>" 꼴로 번호를 붙여 늘어놓는다. 그 순서가 모델이 보는 순서다.
    _titles = [m.group(1).strip() for m in _re.finditer(r"^\s*\d+\.\s*(.+?) by ", _text, _re.M)]
    _by_id = [verified_comparisons[i]["foreign_title"] for i in _ids]
    # 모델은 글에서 "option 1"을 읽고 같은 자리의 ID를 report_comparison에 넣는다. 둘이 어긋나면
    # 말한 비교와 기록된 비교가 달라진다(11/18에 region만 보낸 프로필에서 실제로 어긋났다).
    check(f"{_profile or '프로필 없음'}: 글 순서와 ID 순서가 같다",
          [t[:40] for t in _titles] == [t[:40] for t in _by_id],
          f"글 {[t[:28] for t in _titles]} vs ID {[t[:28] for t in _by_id]}")


print("29. 관람 기록: 켜야 남고, 글자는 한 자도 남지 않는다")
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from server import visit_log  # noqa: E402


class FakeUsage:
    """Gemini의 usage_metadata 모양만 맞춘 것. 숫자는 세션 누적이다(11/18 실측)."""

    def __init__(self, total):
        self.total_token_count = total
        self.prompt_tokens_details = ()
        self.response_tokens_details = ()


def visit_log_run(**envs):
    """환경 변수를 주고 handsfree 한 관람을 돌린 뒤, 남은 기록 줄과 파일 원문을 돌려준다."""
    folder = tempfile.mkdtemp()
    saved = {k: os.environ.get(k) for k in
             ("LIVE_VISIT_LOG", "LIVE_VISIT_DIR", "LIVE_VISIT_SOURCE_KIND", "LIVE_VISIT_SEASON",
              "LIVE_VISIT_GALLERY")}
    os.environ.update({"LIVE_VISIT_DIR": folder, **envs})
    for key in saved:
        if key not in envs and key != "LIVE_VISIT_DIR":
            os.environ.pop(key, None)
    try:
        run([[
            # 인사 턴. 아직 작품을 모른다 — 이 턴의 usage에는 작품 ID가 빈 값이어야 한다.
            [msg(said="Welcome to the gallery."), msg(usage=FakeUsage(2053)), msg(turn_complete=True)],
            [msg(calls=[("report_current_artwork", {"artwork_id": ARTWORK})])],
            [msg(calls=[("report_current_artwork", {"artwork_id": "unknown"})])],
            [msg(calls=[("report_comparison", {"comparison_id": "C_KHD_BRUEGEL"})])],
            [msg(heard="Who painted this and when?"), msg(audio=b"\x01"),
             msg(said="Kim Hong-do painted it in the late eighteenth century."),
             msg(usage=FakeUsage(2522)), msg(interrupted=True), msg(turn_complete=True)],
        ]], expect=9, first=HANDSFREE, linger=0.4)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    raw = "".join(path.read_text(encoding="utf-8")
                  for path in sorted(Path(folder).glob("visits-*.jsonl")))
    return [json.loads(l) for l in raw.splitlines() if l.strip()], raw, folder


rows, raw, folder = visit_log_run()
check("기본값은 꺼짐이다 — 파일을 만들지 않는다",
      rows == [] and list(Path(folder).iterdir()) == [], str(list(Path(folder).iterdir())))

rows, raw, _ = visit_log_run(LIVE_VISIT_LOG="team", LIVE_VISIT_SOURCE_KIND="team_rehearsal",
                             LIVE_VISIT_SEASON="2026-가을", LIVE_VISIT_GALLERY="서화실")
kinds = [r["event"] for r in rows]
check("관람 하나가 visit_start로 시작해 visit_end로 끝난다",
      kinds[:1] == ["visit_start"] and kinds[-1:] == ["visit_end"], str(kinds))
check("작품 인식이 남는다", any(r["event"] == "artwork_identified" and r["artwork_id"] == ARTWORK
                            and r["via"] == "function" for r in rows), str(kinds))
check("unknown은 작품으로 세지 않고 따로 센다",
      sum(r["event"] == "artwork_identified" for r in rows) == 1
      and sum(r["event"] == "artwork_unknown" for r in rows) == 1, str(kinds))
check("비교가 남는다", any(r["event"] == "comparison" and r["comparison_id"] == "C_KHD_BRUEGEL"
                        and r["via"] == "function" for r in rows), str(kinds))
check("끼어들기가 남는다", any(r["event"] == "quality" and r["issue"] == "interrupted" for r in rows),
      str(kinds))
question = next((r for r in rows if r["event"] == "question"), None)
check("질문 한 번이 남는다", question is not None and question["artwork_id"] == ARTWORK
      and question["channel"] == "voice", str(question))
check("라벨과 결과는 아직 빈 값이다(FE3·BE1 결정 전)",
      question is not None and question["label"] == "" and question["outcome"] == "", str(question))
check("첫 음성까지 걸린 시간을 잰다(못 재면 -1)",
      question is not None and isinstance(question["first_audio_ms"], int), str(question))
check("시즌·전시실이 들어간다",
      rows[0]["season_id"] == "2026-가을" and rows[0]["gallery"] == "서화실", str(rows[0]))
check("연결 직후 인사는 질문으로 세지 않는다",
      sum(r["event"] == "question" for r in rows) == 1, str(kinds))
usages = [r for r in rows if r["event"] == "usage"]
check("턴이 끝날 때마다 usage가 남는다", len(usages) == 2, str(usages))
check("사용량은 턴마다의 양이다(누적을 그대로 적지 않는다)",
      [u["total"] for u in usages] == [2053, 469], str(usages))
# 작품 ID가 없으면 "어느 작품 설명이 비싼가"를 알 수 없다. 관람 전체 비용만 나온다.
check("작품을 아는 턴의 usage에 작품 ID가 들어간다",
      len(usages) == 2 and usages[1].get("artwork_id") == ARTWORK, str(usages))
check("작품을 모르는 인사 턴은 작품 ID가 빈 값이다",
      len(usages) == 2 and usages[0].get("artwork_id") == "", str(usages))
check("관람이 왜 끝났는지 남는다", rows[-1]["reason"] in ("phone_closed", "replaced", "phone_idle"),
      str(rows[-1]))

for forbidden in ("Who painted this", "Kim Hong-do", "eighteenth century", "France", "adult"):
    check(f"기록 파일에 {forbidden!r}가 없다", forbidden not in raw)
check("서버 세션 ID가 기록에 없다", not any("session_id" in r for r in rows))
check("벽시계 시각은 visit_start의 10분 버킷 하나뿐이다",
      sum("start_bucket" in r for r in rows) == 1
      and all(len(r["start_bucket"]) == 16 and r["start_bucket"].endswith("0")
              for r in rows if "start_bucket" in r), str(rows[0].get("start_bucket")))
check("모든 줄이 설계에 있는 사건이다", set(kinds) <= set(visit_log.ALLOWED), str(set(kinds)))

print("31. 주입한 비교 목록이 함수 선언·응답·화면·관람 기억에 함께 반영된다")
original_comparisons = relay.comparisons
injected = {**verified_comparisons["C_KHD_BRUEGEL"], "comparison_id": "TEST_INJECTED"}
unverified = {**injected, "comparison_id": "TEST_UNVERIFIED", "verification_status": "draft"}
relay.comparisons = [injected, unverified]
try:
    visit = sessions.create_session()
    got, fake = run([[[
        ART_CALL,
        msg(calls=[("report_comparison", {"comparison_id": "C_KHD_BRUEGEL"})]),
        msg(calls=[("report_comparison", {"comparison_id": "TEST_INJECTED"})]),
        msg(said="Let us compare these paintings.", turn_complete=True),
    ]]], expect=5, first={**HANDSFREE, "session_id": visit.session_id})
    declarations = fake.configs[0].tools[0].function_declarations
    comparison_tool = next(d for d in declarations if d.name == "report_comparison")
    check("함수 선언에는 주입한 검증 비교 ID만 들어간다",
          comparison_tool.parameters.properties["comparison_id"].enum == ["TEST_INJECTED"])
    responses = [r.response for r in fake.session.tool_responses]
    check("작품 함수 결과도 같은 비교 ID를 돌려준다",
          responses[0]["comparison_ids"] == ["TEST_INJECTED"])
    check("기존 전역 목록의 ID는 주입한 목록 밖이므로 거부한다", responses[1]["ok"] is False)
    shown = next(g for g in got if isinstance(g, dict) and g.get("type") == "comparison")
    check("화면 정보와 관람 기억도 주입한 비교를 사용한다",
          shown["comparison_id"] == "TEST_INJECTED"
          and shown["foreign_title"] == injected["foreign_title"]
          and visit.used_comparison_ids == ["TEST_INJECTED"])

    got, fake = run([[[ART_CALL, msg(
        said=f"{injected['foreign_artist']}: {injected['foreign_title']}", turn_complete=True),
    ]]], expect=5, first=HANDSFREE)
    check("받아쓰기에서 찾는 비교도 주입한 목록을 따른다",
          any(isinstance(g, dict) and g.get("type") == "comparison"
              and g.get("comparison_id") == "TEST_INJECTED"
              and g.get("source") == "transcript" for g in got))
finally:
    relay.comparisons = original_comparisons


print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("세션 수명 시험 전부 통과")
