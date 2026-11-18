"""폰 ↔ 우리 서버 ↔ Gemini Live 음성 중계. 운영 서버의 `/ws/live`에 붙는다.

담당: FE1
같이 보는 파일: live_config.py (설정), live_transcript.py (자막),
              live_conversation.py (턴·작품·비교 처리),
              live_context.py (지시문 조각, BE1), prompts.py (LIVE_INSTRUCTION, BE1),
              session.py (관람 기억, BE1), ask.py (build_artwork_context, BE1),
              content.py (작품·비교쌍, BE2), docs/api.md (WS 형식),
              tools/fake_browser_live.py (실제 Gemini로 하는 확인),
              tools/live_frame_recognition.py (Live + 함수 호출 + 사진을 처음 돌려 본 도구),
              tests/test_live_session_lifetime.py (가짜 Gemini로 하는 시험)

왜 중계가 필요한가:
    AGENTS.md는 클라이언트 코드에 API 키를 넣지 못하게 한다. 그래서 폰 브라우저가 Gemini Live에
    직접 붙을 수 없고, 우리 서버가 가운데서 음성을 넘겨주어야 한다.

두 가지 모드(첫 메시지의 "mode"로 고른다, 11/18 T1·T2 계약):
    push(기본, `/live` 시험 페이지):
        버튼을 누르는 동안만 소리를 받는다. 자동 음성 감지를 끄고 speech_start·speech_end로
        말의 경계를 알린다. 연결할 때 받은 작품 한 점으로 고정하고 지시문은 BE1의
        build_live_instruction을 그대로 쓴다. 11/17 동작 그대로다.
    handsfree(AIVY 화면, 11/18 추가):
        버튼 없이 사람과 말하듯 대화한다.
        - 폰이 마이크 PCM을 쉬지 않고 보내고, Gemini의 자동 음성 감지가 말의 시작·끝을 판단한다.
          관람객이 답을 끊으면 Gemini가 interrupted를 주고, 우리는 폰에 그대로 알린다(재생 멈춤).
        - 폰이 3초마다 카메라 사진을 보낸다. 작품은 연결할 때 정하지 않고 Live가 사진으로 알아본다.
        - Live가 함수 두 개를 부른다. report_current_artwork(어느 작품인지) → 우리는 그 작품의
          확인된 사실과 비교 후보를 함수 결과로 돌려준다. report_comparison(어느 비교를 꺼내는지)
          → 우리는 그 비교쌍의 내용을 돌려주고 관람 기억에 남긴다. 그래서 push 모드에서 빈 값이던
          comparison_id가 handsfree에서는 채워진다.
        - 연결되면 Live가 먼저 짧게 인사하고 어디서 왔는지, 어떤 미술을 좋아하는지 묻는다.

폰이 다시 붙을 때(11/18 오후, 스마트글라스·폰 화면 꺼짐 대비):
    폰 WS가 끊겨도 Gemini 재개 핸들과 지금 작품을 session_id별로 이 모듈의 저장소(resume_store)에
    남겨 둔다. 폰이 같은 session_id와 "resume": true로 다시 붙으면 그 핸들로 Gemini 대화를 잇고
    인사하지 않는다(ready.resumed=true). 핸들이 없거나 2시간이 지났거나 거부되면 새 대화로 시작하되
    처음 인사 대신 "다시 연결됐다"고 짧게 말하고, 저장된 작품의 사실을 넘겨 이어 말하게 한다
    (ready.resumed=false). 같은 session_id로 WS가 둘 붙으면 앞의 것을 닫는다.
    저장소는 서버 메모리에만 있다(서버를 다시 켜면 사라진다. 대화 내용은 Gemini 쪽에만 있다).

아직 없는 것:
    - **프로필 변경.** 연결할 때 한 번만 넣는다(11/17 BE1 결정). handsfree에서 관람객이 말로
      출신을 알려 줘도 비교 후보의 순서는 첫 메시지의 profile로 정한다(모델은 후보 둘을 다 본다).
    - 실제 Gemini 동시 접속 한도 확인과 인증(관람별 상태는 분리되어 있다).
    - **에코 처리.** handsfree는 마이크를 계속 열어 두므로 스피커 소리를 마이크가 다시 들으면
      자기 말에 끼어들 수 있다. 서버에서는 막지 않는다(이어폰 또는 브라우저 echoCancellation 전제).
    - 10분을 넘는 실제 관람 길이의 실기기 확인. 아래 재연결은 가짜 Gemini 시험까지만 확인했다.

세션 수명(공식 문서 확인, 2026-11-14 · aistudio.google.com/docs/live-api/session-management):
    - 압축이 없으면 음성 전용 세션은 15분, 음성+영상은 2분에서 끝난다. contextWindowCompression을
      켜면 "무제한"으로 늘어난다고 적혀 있다. 그래서 켜 둔다. handsfree는 사진이 섞이므로 꼭 필요하다.
    - 연결 하나의 수명은 그와 별개로 "약 10분"이고, 연결이 끝나면 세션도 끝난다. 그래서 세션을
      여러 연결에 걸쳐 잇는 sessionResumption이 필요하다.
    - 연결이 곧 닫히기 전에 GoAway가 오고 남은 시간(timeLeft)이 함께 온다. 문서는 미리 오는
      시간을 숫자로 밝히지 않는다. 그래서 '몇 초 전에 온다'고 가정하지 않고 받는 즉시 옮긴다.
    - 재개 핸들은 "마지막 세션 종료 뒤 2시간" 유효하다. 거듭 실패하면 핸들을 버리고 새 대화로
      다시 시작한다(대화 내용은 잃는다).
"""

import asyncio
import base64
import binascii
import json
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.genai import types
from google.genai.errors import APIError

from . import session as sessions
from .ask import build_artwork_context
from .content import load_artworks, load_comparisons
from .gemini_client import make_client
from . import live_config as settings
from . import visit_log
from .live_conversation import LiveConversation
from .live_transcript import feed_said, flush_said

router = APIRouter()
artworks = load_artworks()
comparisons = load_comparisons()
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router.add_event_handler("startup", settings.print_live_config)

# 말의 앞뒤에 넣는 무음(push 모드). 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘린다. 11/11 측정에서
# 취약 문장 5개를 조건별 5회(각 25건) 시험해 완전 일치가 10/25 → 25/25였다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음

HANDLE_GIVE_UP = 3       # 연달아 이 횟수만큼 실패하면 재개 핸들을 버린다
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)

# 폰이 다시 붙을 때 이어 쓸 것. session_id → {"handle", "artwork_id", "updated"(time.time())}.
# 공식 문서(session-management): 재개 핸들은 마지막 세션 종료 뒤 2시간 유효하다. 넘은 것은 버린다.
HANDLE_TTL_S = 2 * 60 * 60
resume_store = {}
# 지금 붙어 있는 폰 WS. session_id → 앞 연결을 닫게 하는 함수. 같은 관람에 WS가 둘이면 Gemini
# 세션도 둘이 되어 서로 다른 대화가 생긴다. 그래서 새 연결이 오면 앞의 것을 닫는다.
active_connections = {}


def saved_resume(session_id):
    """저장된 재개 정보. 2시간이 지났으면 지우고 None."""
    now = time.time()
    for sid in [k for k, v in resume_store.items() if now - v["updated"] > HANDLE_TTL_S]:
        del resume_store[sid]
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
    art = artworks.get(first.get("artwork_id"))
    if art is None and mode == "push":
        await ws.send_text(json.dumps({"type": "error", "message": "unknown artwork"}))
        await ws.close()
        return
    profile = first.get("profile") or {}

    # 관람 기록(FE1). 기본값은 꺼짐이고, LIVE_VISIT_LOG가 team·visitor일 때만 파일을 만든다.
    # 꺼져 있으면 아무것도 하지 않는 기록기가 와서 아래 vlog.event(...) 줄은 그냥 지나간다.
    # 넣을 수 있는 칸은 server/visit_log.py의 ALLOWED에 적혀 있다 — 들은 말·한 말은 넣을 칸이 없다.
    vlog = visit_log.start(mode=mode, model=settings.LIVE_MODEL, voice=settings.LIVE_VOICE,
                           ui_lang=str(profile.get("language") or "en")[:16])

    # 관람 기억. 폰이 /api/session에서 받은 session_id를 보내면 그 관람에 이어 쓴다. 없거나
    # 서버를 다시 켜서 사라졌으면 새로 만들고 ready에 담아 돌려준다(폰이 요약 화면에 쓴다).
    visit = sessions.get_session(first.get("session_id") or "") or sessions.create_session()
    sid = visit.session_id

    # 다시 붙는 폰이면 저장해 둔 재개 핸들과 작품을 이어받는다.
    want_resume = first.get("resume") is True
    saved = saved_resume(sid) if want_resume else None
    if mode == "handsfree" and art is None and saved and saved.get("artwork_id") in artworks:
        art_from_resume = saved["artwork_id"]
    else:
        art_from_resume = ""

    # 같은 관람의 앞 연결을 닫는다(폰이 다시 붙었는데 앞 WS가 아직 살아 있는 경우).
    kicked = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = active_connections.get(sid)
    if previous:
        previous()
    my_kick = lambda: loop.call_soon_threadsafe(kicked.set)  # noqa: E731 (다른 이벤트 루프에서도 불린다)
    active_connections[sid] = my_kick

    conversation = LiveConversation(
        mode=mode, artwork_id=art["artwork_id"] if art else art_from_resume,
        profile=profile, visit=visit, artworks=artworks, comparisons=comparisons,
        resume_store=resume_store, vlog=vlog, saved=saved)
    state = conversation.state
    to_browser = conversation.to_browser
    if mode == "push":
        config = settings.live_config(art, profile, tuple(visit.used_comparison_ids), comparisons)
    else:
        config = settings.handsfree_config(profile, artworks, conversation.verified_comparisons)
    client = make_client()

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
                        # 인사 턴에는 사진을 넣지 않는다. 11/18 측정(포트 8055, 인사만 받는 왕복):
                        # 사진을 같이 넣으면 3/3이 인사 뒤에 모델 속 글을 흘렸고, 한 번은 글이
                        # "(No function call needed, per instructions to greet first.)"였다.
                        # 사진 없이는 1/3이었다. 인사 신호 자체가 "아직 그림 이야기는 하지 말라"고
                        # 적고 있으니, 인사가 끝난 뒤에 최신 1장을 넘긴다.
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
        """한 턴을 읽는다. 돌려주는 값은 왜 끝났는지다: "turn"(답변 끝) 또는 "go_away"(연결 교체).

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
                # 모델은 함수 결과를 받을 때까지 기다린다. 응답은 우리가 직접 보내야 한다.
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
                # 턴마다 여러 번 올 수 있어 마지막 것만 들고 있다가 턴이 끝날 때 한 번 적는다.
                # 이 숫자는 세션 누적이다(11/18 실측: total 2053→2522→3849→4166). 아래에서 차이를 적는다.
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
                    # Gemini가 주는 숫자는 세션 누적이다(11/18 실측: total 2053→2522→3849→4166).
                    # 그대로 적으면 턴마다 더할 수 없으니 앞 턴과의 차이를 적는다.
                    # 그때의 작품을 같이 적는다. 없으면 어느 작품 설명이 비싼지 알 수 없다.
                    # 작품을 아직 모르는 턴(인사)은 빈 값이 된다.
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
        """Live 세션을 열고, 끊기거나 연결 수명이 다하면 핸들로 다시 붙는다. 폰 연결은 끊지 않는다.

        session.receive()는 한 턴이 끝나면 스스로 끝나므로 안쪽에서 다시 부른다. 한 번만 돌리면
        두 번째 질문의 답이 오지 않고, 아무도 Gemini 소켓을 읽지 않아 연결이 끊긴다(11/11에 겪음).

        연결을 바꾸는 경우는 셋이다.
            1) GoAway 예고(연결 약 10분 수명) → 우리가 먼저 옮긴다.
            2) 질문 사이 2분 비활성으로 Gemini가 닫음(1008) → 다시 붙는다.
            3) 핸들이 거부됨(종료 뒤 2시간 지남 등) → 거듭 실패하면 핸들을 버리고 새로 시작한다.
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
                        # 버튼이 없으므로 Live가 먼저 말을 건다(목소리 하나로 통일, 브라우저 음성 인사 없음).
                        # 다시 붙었지만 대화를 잃었으면 인사 대신 돌아왔다고만 말한다.
                        #
                        # state["session"]을 세우기 전에 보낸다. 세우는 순간부터 browser_to_gemini가
                        # 폰의 마이크 PCM과 사진을 send_realtime_input으로 흘리는데, google-genai
                        # 2.34.0 live.py의 send_client_content 주의문이 "같은 대화에서 둘을 섞어 쓰는
                        # 것은 권하지 않으며 예상 밖의 결과가 날 수 있다"고 적고 있다. 인사 신호가
                        # 먼저 닿도록 순서를 정해 둔다.
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
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[live] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                if active_connections.get(sid) is not my_kick:
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
                    # 핸들이 문제일 가능성이 높다(2시간 만료 등). 대화를 잃더라도 도슨트를 살린다.
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

    # 셋 중 하나가 끝나면(폰이 떠났거나 오류) 나머지를 끊는다.
    #
    # 왜 gather가 아닌가: gather는 폰 쪽 루프가 끝나도 나머지를 기다린다. 그러면 관람객이 창을
    # 닫은 뒤에도 Gemini 세션이 자기 수명까지 살아 있고 우리는 그동안 재연결을 계속한다.
    #
    # kicked: 같은 session_id로 새 폰 연결이 오면 켜진다 → 이 연결을 닫는다.
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
        if active_connections.get(sid) is my_kick:
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
        # Gemini 세션은 위에서 작업을 취소하며 닫혔다. 핸들은 남긴다(2시간 시계는 지금부터).
        # 정리하는 몇 초 사이에 새 연결이 이어받아 더 새 핸들을 저장했을 수 있으므로, 저장소의 핸들이
        # 우리 것일 때만 시각을 갱신한다(새 핸들을 옛 핸들로 덮지 않는다).
        entry = resume_store.get(sid)
        if entry is None:
            conversation.save_resume()
        elif entry["handle"] == state["handle"]:
            entry["updated"] = time.time()
        if active_connections.get(sid) is my_kick:
            del active_connections[sid]
        # 관람 기록을 닫는다. 왜 끝났는지만 남긴다(세션 ID는 남기지 않는다).
        vlog.end(reason="phone_idle" if (phone_silent is not None and phone_silent.done()
                                         and not phone_silent.cancelled())
                 else "replaced" if kicked.is_set() else "phone_closed")
    print(f"[live] 폰 연결 끝({sid[:8]}, {mode}). 저장된 핸들 "
          f"{'있음' if (resume_store.get(sid) or {}).get('handle') else '없음'}")
    if phone_silent is not None and phone_silent.done() and not phone_silent.cancelled():
        try:
            await ws.close(code=4001, reason="no input from the phone")
        except Exception:
            pass
    if kicked.is_set():
        print(f"[live] 같은 관람({sid[:8]})의 새 연결이 와서 앞 연결을 닫는다")
        try:
            await ws.close(code=4000, reason="replaced by a newer connection")
        except Exception:
            pass
