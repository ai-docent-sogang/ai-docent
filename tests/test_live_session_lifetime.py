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
import json
import sys
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.genai.errors import APIError

import server.live as relay
import server.session as sessions
from server.app import app as server_app

ARTWORK = "KHD_SSIREUM"
CLOSED_1008 = APIError(1008, {"error": {"code": 1008, "message": "Session closed due to client inactivity"}})


# ── Gemini 자리에 놓는 가짜 ───────────────────────────────────────────────
def msg(*, handle=None, resumable=None, go_away=None, audio=None, said=None,
        heard=None, turn_complete=False, interrupted=False, calls=None):
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
    )


class WaitClientContent:
    """send_client_content가 count번 불린 뒤에야 내보내는 턴."""

    def __init__(self, count, messages):
        self.count, self.messages = count, messages


class FakeSession:
    """대본대로 메시지를 내보내는 가짜 Live 세션. receive()를 부를 때마다 한 턴을 내보낸다."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent = []            # send_realtime_input으로 받은 것
        self.client_content = []  # send_client_content로 받은 것(글 질문, 인사 신호)
        self.tool_responses = []  # send_tool_response로 받은 함수 결과

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def send_client_content(self, **kw):
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
check("push 모드 설정에 목소리가 들어간다", voice == relay.LIVE_VOICE, str(voice))
check("ready에 목소리 이름이 온다", got[0].get("voice") == relay.LIVE_VOICE, str(got[0]))
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
check("같은 목소리를 쓴다", cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == relay.LIVE_VOICE)
hf_instruction = fake.instructions[0]
check("지시문에 BE1 규칙·프로필·11점 후보·함수 규칙이 들어간다",
      "Fact rules" in hf_instruction and "VISITOR PROFILE" in hf_instruction and "France" in hf_instruction
      and "EXHIBITION" in hf_instruction and "report_current_artwork" in hf_instruction, hf_instruction[:80])
check("연결되면 Live가 먼저 인사하게 신호를 보낸다",
      len(fake.session.client_content) == 1
      and relay.GREETING_CUE in fake.session.client_content[0]["turns"].parts[0].text)
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
      and set(art_result["comparison_ids"]) == {"C_KHD_BRUEGEL", "C_KHD_HOKUSAI_MANGA"}, str(art_result.get("comparison_ids")))
check("다른 작품의 비교쌍은 거절한다", responses[1].response.get("ok") is False, str(responses[1].response))
check("지금 작품의 검증된 비교쌍은 받는다", responses[2].response.get("ok") is True
      and responses[2].response.get("similarities"), str(responses[2].response)[:120])
arts = [g for g in got if isinstance(g, dict) and g.get("type") == "artwork"]
comps = [g for g in got if isinstance(g, dict) and g.get("type") == "comparison"]
check("폰에 artwork를 보낸다", arts and arts[0]["artwork_id"] == ARTWORK and arts[0]["artwork_title"], str(arts))
check("폰에 comparison은 받은 것 하나만 보낸다",
      comps == [{"type": "comparison", "comparison_id": "C_KHD_BRUEGEL", "artwork_id": ARTWORK}], str(comps))
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
      cue.startswith(relay.RECONNECT_CUE) and relay.GREETING_CUE not in cue, cue[:80])

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

print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("세션 수명 시험 전부 통과")
