"""Gemini Live WebSocket 중계. 담당: FE1.

push는 버튼으로 발화 경계를 전달하고, handsfree는 연속 음성·사진과 자동 발화 감지를 사용한다.
폰 재접속과 Gemini 연결 교체 시 관람 기억과 재개 핸들을 유지한다.
API 키는 서버에서만 사용하며 음성·프레임은 파일에 저장하지 않는다.

설정: live_config.py / 자막: live_transcript.py / 관람 처리: live_conversation.py
통신 계약: docs/api.md / 검증: tests/test_live_session_lifetime.py
"""

import asyncio
import base64
import binascii
import json
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.genai import types
from google.genai.errors import APIError

from .. import session as sessions
from ..content import build_artwork_context, load_artworks, load_comparisons
from ..gemini_client import make_client
from . import live_config as settings
from .. import on_view
from .. import visit_log
from .live_conversation import LiveConversation
from .live_transcript import feed_said, flush_said


@asynccontextmanager
async def lifespan(app):
    settings.print_live_config()
    cleaner = asyncio.create_task(clean_idle_sessions())
    try:
        yield
    finally:
        cleaner.cancel()
        with suppress(asyncio.CancelledError):
            await cleaner


router = APIRouter(lifespan=lifespan)
artworks = load_artworks()
comparisons = load_comparisons()
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

# push 모드에서 첫 단어와 끝 단어가 잘리지 않도록 발화 전후에 무음을 넣는다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음

HANDLE_GIVE_UP = 3       # 연달아 이 횟수만큼 실패하면 재개 핸들을 버린다
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)

# 재개 정보: session_id → {handle, artwork_id, updated}. 종료 후 2시간까지 유지한다.
HANDLE_TTL_S = 2 * 60 * 60
CLEANUP_INTERVAL_S = 60
resume_store = {}
# 연결 정보: session_id → {close, state, reconnects}. 같은 관람에는 연결 하나만 유지한다.
active_connections = {}
# 관람 기록: session_id → VisitLog. 폰이 끊겼다 다시 붙어도 같은 기록을 이어 쓴다. 재개 정보와
# 수명이 같아서 관람이 끝날 때(END VISIT)와 만료될 때만 finish_visit_log로 닫고 지운다.
visit_logs = {}


def finish_visit_log(session_id, reason):
    """관람이 정말 끝났다. 기록을 닫고 지운다. 폰 연결만 끊긴 때는 부르지 않는다."""
    log = visit_logs.pop(session_id, None)
    if log:
        log.end(reason=reason)


def cleanup_expired():
    """기억과 재개 핸들을 함께 청소한다. 접속 중인 관람은 삭제하지 않는다."""
    for sid in sessions.expire_idle_sessions(HANDLE_TTL_S, active_connections):
        resume_store.pop(sid, None)
        finish_visit_log(sid, "expired")
    now = time.time()
    for sid, entry in list(resume_store.items()):
        if sid not in active_connections and now - entry["updated"] > HANDLE_TTL_S:
            resume_store.pop(sid, None)
            finish_visit_log(sid, "expired")


async def clean_idle_sessions():
    while True:
        cleanup_expired()
        await asyncio.sleep(CLEANUP_INTERVAL_S)


def end_visit(session_id):
    """명시적으로 끝낸 관람은 즉시 폐기하고, 아직 남은 연결도 닫는다."""
    sessions.end_session(session_id)
    resume_store.pop(session_id, None)
    finish_visit_log(session_id, "visit_ended")
    connection = active_connections.get(session_id)
    if connection:
        connection["close"]()


@router.get("/live/status")
async def live_status():
    """운영 확인용 상태. 질문·답변·재개 핸들·전체 세션 ID는 내보내지 않는다."""
    cleanup_expired()
    now = time.monotonic()
    return {
        "active_visits": len(active_connections),
        "visits": [{"session_id": sid[:4], "artwork_id": c["state"]["artwork_id"],
                    "idle_s": round(max(0, now - c["state"]["last_input"]), 1),
                    "gemini_connected": c["state"]["session"] is not None,
                    "reconnects": c["reconnects"]}
                   for sid, c in active_connections.items()],
        "saved_resumes": len(resume_store),
        "model": settings.LIVE_MODEL, "voice": settings.LIVE_VOICE,
        "frame_policy": settings.FRAME_POLICY,
    }


def saved_resume(session_id):
    """저장된 재개 정보. 2시간이 지났으면 지우고 None."""
    cleanup_expired()
    return resume_store.get(session_id)


@router.get("/live")
def live_test_page():
    """Live 음성 시험 페이지. 운영 화면이 아니다(관람객 화면은 FE2의 `/`).

    아이폰 Safari에서 마이크 16kHz 전송과 24kHz 재생이 되는지 확인하는 데 쓴다.
    """
    return FileResponse(STATIC_DIR / "live_test.html")


async def send_silence(session):
    await session.send_realtime_input(
        audio=types.Blob(data=SILENCE_PCM, mime_type="audio/pcm;rate=16000"))


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    await ws.accept()

    # 첫 메시지: 모드, 관람객 프로필, 이어 쓸 관람 세션. push 모드는 작품도 받는다.
    # profile과 session_id는 없어도 된다(시험 페이지는 artwork_id만 보낸다).
    first = json.loads(await ws.receive_text())
    mode = "handsfree" if first.get("mode") == "handsfree" else "push"
    # 운영 페이지에서 끈 작품을 여기서 한 번 뺀다. 연결마다 다시 거르므로 모듈 수준 목록이
    # app.py가 주입한 것이든 이 파일이 스스로 읽은 것이든 필터가 새지 않는다.
    visible = on_view.visible(artworks)
    art = visible.get(first.get("artwork_id"))
    if art is None and mode == "push":
        await ws.send_text(json.dumps({"type": "error", "message": "unknown artwork"}))
        await ws.close()
        return
    profile = first.get("profile") or {}

    # 관람 기억. 폰이 /api/session에서 받은 session_id를 보내면 그 관람에 이어 쓴다. 없거나
    # 서버를 다시 켜서 사라졌으면 새로 만들고 ready에 담아 돌려준다(폰이 요약 화면에 쓴다).
    visit = sessions.get_session(first.get("session_id") or "") or sessions.create_session()
    sid = visit.session_id

    # 관람 기록은 관람 하나에 하나다. 기록은 기본 비활성이고 허용 필드는 visit_log.ALLOWED에 있다.
    vlog = visit_logs.get(sid)
    if vlog is None:
        vlog = visit_logs[sid] = visit_log.start(
            mode=mode, model=settings.LIVE_MODEL, voice=settings.LIVE_VOICE,
            ui_lang=str(profile.get("language") or "en")[:16])

    # 다시 붙는 폰이면 저장해 둔 재개 핸들과 작품을 이어받는다.
    want_resume = first.get("resume") is True
    saved = saved_resume(sid) if want_resume else None
    if mode == "handsfree" and art is None and saved and saved.get("artwork_id") in visible:
        art_from_resume = saved["artwork_id"]
    else:
        art_from_resume = ""

    conversation = LiveConversation(
        mode=mode, artwork_id=art["artwork_id"] if art else art_from_resume,
        profile=profile, visit=visit, artworks=visible, comparisons=comparisons,
        resume_store=resume_store, vlog=vlog, saved=saved)
    state = conversation.state
    to_browser = conversation.to_browser
    if mode == "push":
        config = settings.live_config(art, profile, tuple(visit.used_comparison_ids), comparisons)
    else:
        config = settings.handsfree_config(profile, visible, conversation.verified_comparisons)
    client = make_client()

    # 설정과 클라이언트 생성에 성공한 뒤 등록한다. 같은 관람의 이전 연결은 닫는다.
    kicked = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = active_connections.get(sid)
    if previous:
        previous["close"]()
    connection = {"close": lambda: loop.call_soon_threadsafe(kicked.set),
                  "state": state, "reconnects": 0}
    active_connections[sid] = connection

    async def send_frame(session, jpeg):
        await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))

    async def end_opening_turn(session):
        """인사 턴이 끝났다. 그동안 들고 있던 사진 1장을 바로 넘긴다."""
        if state["opening_turn"]:
            state["opening_turn"] = False
            state["first_frame_sent"] = True   # on_speech: 이 1장이 그 연결의 첫 사진이다
            await send_held_frame(session)

    async def send_held_frame(session):
        """on_speech 정책: 들고 있던 최신 사진 1장을 넘긴다(넘긴 뒤 비운다. 같은 사진을 거듭 넣지 않는다)."""
        jpeg, state["latest_frame"] = state["latest_frame"], None
        if jpeg:
            await send_frame(session, jpeg)

    async def browser_to_gemini():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            state["last_input"] = time.monotonic()
            session = state["session"]
            data = None
            if msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
                if data.get("type") == "ping":
                    continue    # 살아 있다는 신호. 받기만 하고 Gemini로 보내지 않는다.
                if mode == "handsfree" and data.get("type") == "frame":
                    try:
                        jpeg = base64.b64decode(data.get("jpeg") or "", validate=True)
                    except (binascii.Error, ValueError):
                        continue
                    if not jpeg:
                        continue
                    data = {"type": "frame", "jpeg_bytes": jpeg}
                    if state["opening_turn"]:
                        # 인사 중에는 사진을 보류한다. 사진 입력이 인사 자막의 내부 지시문 노출을 유발할 수 있다.
                        state["latest_frame"] = jpeg
                        continue
                    if settings.FRAME_POLICY == "on_speech":
                        # 최신 1장만 들고 있는다. 연결 직후 첫 1장만 바로 넘긴다.
                        state["latest_frame"] = jpeg
                        if session is None or state["first_frame_sent"]:
                            continue
                        state["first_frame_sent"] = True
                        state["latest_frame"] = None
            if session is None:
                # 재연결 중. 이 조각은 버린다. push는 버튼 신호마다 다시 눌러 달라고 알린다.
                # handsfree는 사진이 3초마다 오므로 글 질문에만 알린다(소리·사진은 조용히 버린다).
                if data is not None and (mode == "push" or data.get("type") == "text"):
                    to_browser.put_nowait(("text", {"type": "reconnecting"}))
                continue
            try:
                if msg.get("bytes") is not None:           # 폰 마이크 PCM 16kHz
                    await session.send_realtime_input(
                        audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                elif data is None:
                    continue
                elif mode == "push":
                    kind = data.get("type")
                    if kind == "speech_start":   # 버튼을 누른 순간
                        await session.send_realtime_input(activity_start=types.ActivityStart())
                        await send_silence(session)  # 첫 단어가 잘리지 않게 여유를 준다
                    elif kind == "speech_end":   # 버튼에서 손을 뗀 순간 → 여기서 답을 만들기 시작한다
                        await send_silence(session)  # 끝 단어가 잘리지 않게
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
                elif data.get("type") == "frame":    # handsfree: 카메라 사진(저장하지 않는다)
                    await send_frame(session, data["jpeg_bytes"])
                elif data.get("type") == "text":     # handsfree: 글로 묻기
                    text = (data.get("text") or "").strip()
                    if text:
                        if settings.FRAME_POLICY == "on_speech":
                            await send_held_frame(session)   # 질문하는 순간의 사진
                        state["heard"] += text
                        state["channel"] = "text"
                        state["heard_at"] = time.monotonic()
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=text)]),
                            turn_complete=True)
            except Exception as e:
                # 세션이 막 끊긴 경우. 바깥 루프가 다시 붙을 때까지 흘려보낸다.
                print(f"[live] 보내기 실패(재연결 대기): {e!r}"[:200])
                state["session"] = None

    async def read_one_turn(session):
        """Gemini 턴을 수신하고 종료 원인("turn" 또는 "go_away")을 반환한다.

        GoAway를 받은 뒤에도 답변이 나오는 중이면 끝까지 읽고 나서 옮긴다. 남은 시간을 문서가
        숫자로 밝히지 않으므로 '아직 여유가 있다'고 믿고 기다리지는 않는다.
        """
        going_away = False
        async for m in session.receive():
            if m.session_resumption_update and m.session_resumption_update.new_handle:
                # resumable이 꺼진 업데이트는 그 시점으로 되돌릴 수 없다는 뜻이므로 받지 않는다.
                if m.session_resumption_update.resumable is not False:
                    state["handle"] = m.session_resumption_update.new_handle
                    conversation.save_resume()
            if m.go_away:
                print(f"[live] GoAway: 남은 시간 {m.go_away.time_left}"
                      f"{' (답변 중 — 턴을 끝내고 옮긴다)' if state['turn_open'] else ''}")
                going_away = True
                if not state["turn_open"]:
                    return "go_away"
            if m.tool_call:
                # 모델의 함수 호출마다 서버가 결과를 전송한다.
                responses = []
                for call in m.tool_call.function_calls or []:
                    result = conversation.answer_tool_call(call)
                    print(f"[live] 함수 {call.name}({json.dumps(call.args or {}, ensure_ascii=False)})"
                          f" → {result.get('artwork_id') or result.get('comparison_id') or result.get('error', '')}"[:200])
                    responses.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
                if responses:
                    await session.send_tool_response(function_responses=responses)
            activity = getattr(m, "voice_activity", None)
            if activity is not None:
                kind = getattr(activity, "voice_activity_type", None)
                name = str(getattr(kind, "name", kind) or "")
                if "END" in name.upper():
                    state["speech_end_at"] = time.monotonic()
            if getattr(m, "usage_metadata", None) is not None:
                # 누적 사용량 업데이트 중 마지막 값을 턴 종료 시 기록한다.
                state["usage"] = m.usage_metadata
            c = m.server_content
            if c is None:
                continue
            if c.interrupted:
                # 관람객이 답을 끊었다. 폰은 재생 중인 소리를 바로 멈춰야 한다.
                conversation.push_said(flush_said(state))
                await end_opening_turn(session)
                to_browser.put_nowait(("text", {"type": "interrupted"}))
                vlog.event("quality", issue="interrupted")
            if c.input_transcription and c.input_transcription.text:
                # 관람객이 말을 시작했으면 인사 턴은 끝난 것으로 본다(사진을 더 들고 있지 않는다).
                await end_opening_turn(session)
                if mode == "handsfree" and settings.FRAME_POLICY == "on_speech" and not state["turn_frame_sent"]:
                    # 이번 턴의 첫 받아쓰기 = 관람객이 말을 시작했다. 그때의 사진 1장을 넘긴다.
                    # (state["heard"]로 판단하지 않는다: 추임새에 Live가 침묵하면 heard가 다음 턴까지 남는다)
                    state["turn_frame_sent"] = True
                    await send_held_frame(session)
                state["heard"] += c.input_transcription.text
                state["heard_at"] = time.monotonic()
                state["channel"] = state["channel"] or "voice"
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                state["turn_open"] = True
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        if state["first_audio_at"] is None:
                            state["first_audio_at"] = time.monotonic()
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                state["turn_open"] = True
                conversation.push_said(feed_said(state, c.output_transcription.text))
            if c.turn_complete:
                state["turn_open"] = False
                state["turn_frame_sent"] = False
                conversation.push_said(flush_said(state))
                await end_opening_turn(session)
                conversation.remember_turn()
                if state["usage"] is not None:
                    # 사용량은 Gemini 세션의 누적값이므로 직전 값과의 차이를 작품별로 기록한다.
                    now_usage = visit_log.usage_fields(state["usage"])
                    vlog.event("usage", artwork_id=state["artwork_id"],
                               **{k: max(0, v - state["usage_seen"].get(k, 0))
                                  for k, v in now_usage.items()})
                    state["usage_seen"] = now_usage
                    state["usage"] = None
                to_browser.put_nowait(("text", {"type": "turn_complete"}))
                if going_away:
                    return "go_away"
        # receive()가 한 턴을 다 내보내고 스스로 끝났다.
        return "go_away" if going_away else "turn"

    def leave_session(kept_conversation=True, announce=True):
        """Gemini 연결을 떠날 때 폰 쪽을 정리한다. 답변 도중이면 턴을 닫아 버튼을 풀어 준다.

        announce=False: 아직 ready를 보내기 전(처음 붙기가 실패함)이라 폰에 reconnecting을 알리지 않는다.
        """
        state["session"] = None
        state["opening_turn"] = False   # 연결이 바뀌면 사진을 더 들고 있지 않는다
        if state["turn_open"]:
            state["turn_open"] = False
            conversation.push_said(flush_said(state))
            conversation.remember_turn()  # 반쯤 받은 답도 들려준 만큼은 기록에 남긴다
            to_browser.put_nowait(("text", {"type": "turn_complete"}))
        if announce:
            to_browser.put_nowait(("text", {
                "type": "reconnecting", "kept_conversation": kept_conversation}))
            vlog.event("quality", issue="reconnect", kept_conversation=kept_conversation)

    def first_cue(resumed):
        """처음 붙었을 때 Live에 보낼 신호. 대화를 이었으면 없음."""
        if mode != "handsfree" or resumed:
            return None
        if not want_resume:
            return settings.GREETING_CUE
        cue = settings.RECONNECT_CUE
        known = artworks.get(state["artwork_id"])
        if known:
            # 대화는 잃었지만 어느 그림 앞이었는지는 안다. 함수 호출 전에도 그 작품으로 이어 말하게 사실을 넘긴다.
            cue += (f"\n[The visitor was looking at {state['artwork_id']}. Until the camera shows otherwise, "
                    f"talk about it using only these facts.]\n{build_artwork_context(known)}")
        return cue

    async def gemini_sessions():
        """Gemini 연결을 열고 GoAway·비활성 종료·핸들 거부 시 재연결한다.

receive()는 한 턴마다 끝나므로 연결이 유지되는 동안 반복해서 읽는다.
핸들 거부가 이어지면 핸들을 버리고 새 대화를 시작한다.
"""
        first_time = True
        fails = 0           # 연달아 실패한 횟수. 재연결이 빈 바퀴를 돌지 않게 쉬는 시간을 늘린다.
        while True:
            had_handle = state["handle"] is not None
            config.session_resumption = types.SessionResumptionConfig(handle=state["handle"])
            try:
                async with client.aio.live.connect(model=settings.LIVE_MODEL, config=config) as session:
                    opened = time.monotonic()
                    state["first_frame_sent"] = False   # on_speech: 새 연결마다 첫 사진 1장은 바로 넘긴다
                    resumed = want_resume and had_handle
                    cue = first_cue(resumed) if first_time else None
                    if cue:
                        # SDK의 입력 전송 순서를 지키기 위해 인사 신호를 먼저 보낸 뒤 마이크·사진 전송을 허용한다.
                        state["opening_turn"] = True
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=cue)]),
                            turn_complete=True)
                    state["session"] = session
                    to_browser.put_nowait(("text", {
                        "type": "ready" if first_time else "reconnected",
                        "model": settings.LIVE_MODEL,
                        "mode": mode,
                        "voice": settings.LIVE_VOICE,
                        **({"artwork_title": art["title_en"]} if art else {}),
                        "session_id": visit.session_id,
                        # 핸들 없이 새로 붙었으면 앞 대화를 잃었다는 뜻이다. 폰이 안내를 바꿀 수 있게 알린다.
                        # 폰이 resume으로 다시 붙었을 때만: 앞 대화를 이었는지
                        **({"resumed": resumed} if first_time and want_resume else {}),
                        **({} if first_time else {"kept_conversation": had_handle})}))
                    if first_time and want_resume and resumed:
                        vlog.event("quality", issue="resumed", kept_conversation=True)
                    if not first_time:
                        connection["reconnects"] += 1
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[live] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                if active_connections.get(sid) is not connection:
                    # 이 관람은 이미 새 폰 연결이 이어받았다(같은 핸들로 붙으면 Gemini가 앞 세션을 닫는다).
                    # 여기서 다시 붙으면 새 연결의 대화를 빼앗으므로 그만둔다.
                    print(f"[live] 세션 종료 {e.code}: 새 연결이 이어받아 이 연결은 다시 붙지 않는다")
                    return
                # 1008 비활성, 연결 수명 초과, 핸들 거부 등.
                fails += 1
                drop_handle = had_handle and fails >= HANDLE_GIVE_UP
                print(f"[live] 세션 종료 {e.code}: {e.message}. "
                      f"다시 붙는다(핸들 {'있음' if state['handle'] else '없음'}, 연달아 실패 {fails})"
                      + (" — 핸들을 버리고 새 대화로 시작한다" if drop_handle else ""))
                if drop_handle:
                    # 재개 실패가 반복되면 만료 가능성이 있는 핸들을 버리고 새 대화로 전환한다.
                    state["handle"] = None
                leave_session(kept_conversation=not drop_handle, announce=not first_time)
                await asyncio.sleep(min(0.5 * 2 ** (fails - 1), RECONNECT_WAIT_MAX))

    async def queue_to_browser():
        """줄에 쌓인 것을 폰으로 보낸다. 느려도 Gemini 읽기를 막지 않는다."""
        while True:
            kind, payload = await to_browser.get()
            if kind == "bytes":
                await ws.send_bytes(payload)
            else:
                await ws.send_text(json.dumps(payload))

    # 폰 종료·오류·연결 교체 중 하나가 발생하면 나머지 작업도 취소한다.
    tasks = [asyncio.create_task(f()) for f in (browser_to_gemini, gemini_sessions, queue_to_browser)]
    tasks.append(asyncio.create_task(kicked.wait()))

    async def phone_watchdog():
        """handsfree: 폰이 PHONE_IDLE_S초 동안 아무것도 보내지 않으면 죽은 연결로 보고 끝낸다."""
        while True:
            idle = time.monotonic() - state["last_input"]
            if idle >= settings.PHONE_IDLE_S:
                print(f"[live] 폰이 {idle:.0f}초 동안 아무것도 보내지 않아 죽은 연결로 보고 닫는다({sid[:8]})")
                vlog.event("quality", issue="phone_idle_close")
                return
            await asyncio.sleep(min(settings.PHONE_IDLE_S - idle, 1.0))

    phone_silent = None
    if mode == "handsfree":
        phone_silent = asyncio.create_task(phone_watchdog())
        tasks.append(phone_silent)
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # 이 관람의 지금 연결에서 바로 뺀다. 아래 정리(Gemini 연결 닫기)는 몇 초 걸릴 수 있는데,
        # 그 사이 폰이 다시 붙으면 이미 떠난 연결을 '앞 연결'로 잘못 닫으려 하게 된다.
        if active_connections.get(sid) is connection:
            del active_connections[sid]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                print(f"[live] 중계 종료: {t.exception()!r}"[:300])
    except WebSocketDisconnect:
        pass
    finally:
        # 종료 시점부터 재개 유효 시간을 센다. 새 연결의 핸들은 덮어쓰지 않는다.
        ended = sessions.get_session(sid) is not visit
        phone_idle = (phone_silent is not None and phone_silent.done()
                      and not phone_silent.cancelled())
        if not ended:
            entry = resume_store.get(sid)
            if entry is None:
                conversation.save_resume()
            elif entry["handle"] == state["handle"]:
                entry["updated"] = time.time()
        else:
            resume_store.pop(sid, None)
        if active_connections.get(sid) is connection:
            del active_connections[sid]
        # 연결이 끊기는 것은 관람이 끝나는 것이 아니다. 관람이 사라졌을 때만 기록을 닫고,
        # 그 밖에는 연결이 왜 닫혔는지만 남긴다(phone_idle은 감시 작업이 이미 남겼다).
        # 기록에는 세션 ID 없이 사유만 넣는다.
        if ended:
            finish_visit_log(sid, "visit_ended")
        elif not phone_idle:
            vlog.event("quality", issue="replaced" if kicked.is_set() else "phone_closed")
    print(f"[live] 폰 연결 끝({sid[:8]}, {mode}). 저장된 핸들 "
          f"{'있음' if (resume_store.get(sid) or {}).get('handle') else '없음'}")
    if phone_idle:
        try:
            await ws.close(code=4001, reason="no input from the phone")
        except Exception:
            pass
    if kicked.is_set():
        try:
            await ws.close(code=1000 if ended else 4000,
                           reason="visit ended" if ended else "replaced by a newer connection")
        except Exception:
            pass
