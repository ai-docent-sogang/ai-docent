"""폰 ↔ 우리 서버 ↔ Gemini Live 음성 중계. 운영 서버의 `/ws/live`에 붙는다.

담당: FE1
같이 보는 파일: live_context.py (지시문, BE1), session.py (관람 기억, BE1), content.py (작품·비교쌍, BE2),
              docs/api.md (WS 형식), docs/11-18_통합_인터페이스.md 1장 (구현 주의사항),
              tools/live_relay_spike.py (이 파일을 쓰는 시험 서버),
              tests/test_live_session_lifetime.py (가짜 Gemini로 세션 수명 시험)

왜 중계가 필요한가:
    AGENTS.md는 클라이언트 코드에 API 키를 넣지 못하게 한다. 그래서 폰 브라우저가 Gemini Live에
    직접 붙을 수 없고, 우리 서버가 가운데서 음성을 넘겨주어야 한다.

11/17에 `tools/live_relay_spike.py`에서 옮겨 왔다. 옮기면서 더한 것은 둘이다.
    ① 지시문을 BE1의 `build_live_instruction`으로 바꿨다. 이전에는 `ASK_INSTRUCTION`(작품 한 점,
       비교 없음)을 써서 "외국 작품과 비교"가 빠져 있었다. 이제 프로필과 검증된 비교 후보가 들어간다.
    ② 턴이 끝날 때 `session.record_turn`을 부른다. 이전에는 세션을 전혀 쓰지 않아 관람 기억이
       쌓이지 않았고, 폰의 관람 요약 화면(본 작품 수)이 비어 있었다. BE1 파일은 고치지 않고 부른다.

아직 없는 것(11/18 범위 밖이거나 미정):
    - **비교쌍 사용 기록.** `record_turn`에 `comparison_id`를 빈 값으로 넘긴다. Live는 음성으로
      답하므로 어떤 비교를 썼는지 구조화된 값으로 알 수 없다(`/api/turn`은 받는다). 요약 화면의
      비교 수는 Live 경로에서 0으로 남는다. 함수 호출로 받는 방법이 있고(11/17에 프레임 인식으로
      동작 확인) 그건 12/1 범위로 둔다. 지금 추측해서 채우지 않는다.
    - **작품 변경.** 연결할 때 받은 작품 한 점으로 고정이다. Live는 연결 시 system_instruction이
      박히므로, 바꾸려면 연결을 새로 열거나 11점 맥락을 모두 넣어야 한다. 어느 쪽이 나은지
      측정하지 않았다.
    - **프로필 변경.** 연결할 때 한 번만 넣는다(11/17 BE1 결정).
    - 여러 관람객 동시 접속과 인증(11/13 팀장 결정, 12/1 범위), 에코 처리.
    - 10분을 넘는 실제 관람 길이의 실기기 확인. 아래 재연결은 가짜 Gemini 시험까지만 확인했다.

세션 수명(공식 문서 확인, 2026-11-14 · aistudio.google.com/docs/live-api/session-management):
    - 압축이 없으면 음성 전용 세션은 15분, 음성+영상은 2분에서 끝난다. contextWindowCompression을
      켜면 "무제한"으로 늘어난다고 적혀 있다. 그래서 켜 둔다.
    - 연결 하나의 수명은 그와 별개로 "약 10분"이고, 연결이 끝나면 세션도 끝난다. 그래서 세션을
      여러 연결에 걸쳐 잇는 sessionResumption이 필요하다.
    - 연결이 곧 닫히기 전에 GoAway가 오고 남은 시간(timeLeft)이 함께 온다. 문서는 미리 오는
      시간을 숫자로 밝히지 않는다. 그래서 '몇 초 전에 온다'고 가정하지 않고 받는 즉시 옮긴다.
    - 재개 핸들은 "마지막 세션 종료 뒤 2시간" 유효하다. 거듭 실패하면 핸들을 버리고 새 대화로
      다시 시작한다(대화 내용은 잃는다).
"""

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.genai import types
from google.genai.errors import APIError

from . import session as sessions
from .content import load_artworks, load_comparisons
from .gemini_client import make_client
from .live_context import build_live_instruction

router = APIRouter()
artworks = load_artworks()
comparisons = load_comparisons()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# 음성 모델은 요청-응답 모델과 다르다(.env의 GEMINI_MODEL은 /api/turn·/api/ask가 쓴다).
LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")

# 말의 앞뒤에 넣는 무음. 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘린다. 11/11 측정에서
# 취약 문장 5개를 조건별 5회(각 25건) 시험해 완전 일치가 10/25 → 25/25였다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음

HANDLE_GIVE_UP = 3       # 연달아 이 횟수만큼 실패하면 재개 핸들을 버린다
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)


@router.get("/live")
def live_test_page():
    """Live 음성 시험 페이지. 운영 화면이 아니다(관람객 화면은 FE2의 `/`).

    아이폰 Safari에서 마이크 16kHz 전송과 24kHz 재생이 되는지 확인하는 데 쓴다.
    """
    return FileResponse(STATIC_DIR / "live_test.html")


async def send_silence(session):
    await session.send_realtime_input(
        audio=types.Blob(data=SILENCE_PCM, mime_type="audio/pcm;rate=16000"))


def live_config(art, profile, used_ids):
    """Live 연결 설정. 지시문은 BE1의 build_live_instruction이 만든다."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_live_instruction(art, comparisons, profile, used_ids),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # 자동 음성 감지(VAD)를 끄고 말의 시작·끝을 우리가 알려 준다.
        #
        # 왜(11/11 아이폰 시험에서 두 번째 질문부터 답이 오지 않았다):
        #   기본값은 모델이 '끊기지 않는' 음성 흐름을 들으면서 침묵으로 말의 끝을 판단한다. 그런데
        #   우리 화면은 버튼을 누르는 동안만 소리를 보내므로 침묵 자체가 전달되지 않는다. 공식 문서는
        #   이런 누르고 말하기 방식에는 자동 감지를 끄고 activityStart·activityEnd로 경계를 알려
        #   주라고 안내한다(그 모드에서는 audioStreamEnd를 보내지 않는다).
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        ),
        # 끊겼을 때 대화 내용을 유지한 채 다시 붙기 위한 핸들을 받아 둔다.
        session_resumption=types.SessionResumptionConfig(),
        # 음성 전용 세션의 15분 제한을 없앤다. 값을 비워 두는 이유: 공식 문서 예시가 기본값만 쓰고
        # 트리거 토큰 수에 권장값을 주지 않는다. 우리 측정값도 없으므로 숫자를 지어내지 않는다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    await ws.accept()

    # 첫 메시지: 어느 작품인지, 관람객 프로필, 이어 쓸 관람 세션.
    # profile과 session_id는 없어도 된다(시험 페이지는 artwork_id만 보낸다).
    first = json.loads(await ws.receive_text())
    art = artworks.get(first.get("artwork_id"))
    if art is None:
        await ws.send_text(json.dumps({"type": "error", "message": "unknown artwork"}))
        await ws.close()
        return
    profile = first.get("profile") or {}

    # 관람 기억. 폰이 /api/session에서 받은 session_id를 보내면 그 관람에 이어 쓴다. 없거나
    # 서버를 다시 켜서 사라졌으면 새로 만들고 ready에 담아 돌려준다(폰이 요약 화면에 쓴다).
    visit = sessions.get_session(first.get("session_id") or "") or sessions.create_session()

    config = live_config(art, profile, tuple(visit.used_comparison_ids))
    client = make_client()

    # 지금 연결된 Live 세션과 재개 핸들. 재연결하면 session만 바뀌고 폰과의 연결은 그대로 둔다.
    #   turn_open: 답변을 내보내는 중인지. 답변 도중에 연결이 옮겨 가면 폰은 turn_complete를
    #              받지 못해 버튼이 잠긴 채로 남는다. 그래서 옮기기 전에 턴을 닫아 준다.
    #   heard/said: 이번 턴의 질문과 답을 모아 둔다. 턴이 끝나면 관람 기억에 넣는다.
    state = {"session": None, "handle": None, "turn_open": False, "heard": "", "said": ""}

    # 폰으로 보낼 것을 담아 두는 줄. Gemini를 읽는 일과 폰으로 보내는 일을 떼어 놓는다.
    # 붙여 두면 폰 전송이 느릴 때 Gemini 쪽 소켓을 읽지 못해 연결이 위험해진다(11/11에 끊겼다).
    to_browser = asyncio.Queue()

    def remember_turn():
        """이번 턴을 관람 기억에 넣는다. BE1의 session.record_turn을 부르기만 한다.

        comparison_id를 빈 값으로 넘긴다. Live는 음성으로 답하므로 어떤 비교를 썼는지 알 수 없다.
        추측해서 채우면 요약 화면에 쓰지 않은 비교가 올라간다(머리말의 '아직 없는 것' 참고).
        """
        said = state["said"].strip()
        if not said:
            return
        visit.record_turn(state["heard"].strip(), SimpleNamespace(
            artwork_id=art["artwork_id"], comparison_id="", reply=said))
        state["heard"] = state["said"] = ""

    async def browser_to_gemini():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            session = state["session"]
            if session is None:
                # 재연결 중. 이 조각은 버린다(관람객에게는 다시 눌러 달라고 알린다).
                if msg.get("text"):
                    to_browser.put_nowait(("text", {"type": "reconnecting"}))
                continue
            try:
                if msg.get("bytes") is not None:           # 폰 마이크 PCM 16kHz
                    await session.send_realtime_input(
                        audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                elif msg.get("text"):
                    kind = json.loads(msg["text"]).get("type")
                    if kind == "speech_start":   # 버튼을 누른 순간
                        await session.send_realtime_input(activity_start=types.ActivityStart())
                        await send_silence(session)  # 첫 단어가 잘리지 않게 여유를 준다
                    elif kind == "speech_end":   # 버튼에서 손을 뗀 순간 → 여기서 답을 만들기 시작한다
                        await send_silence(session)  # 끝 단어가 잘리지 않게
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
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
            if m.go_away:
                print(f"[live] GoAway: 남은 시간 {m.go_away.time_left}"
                      f"{' (답변 중 — 턴을 끝내고 옮긴다)' if state['turn_open'] else ''}")
                going_away = True
                if not state["turn_open"]:
                    return "go_away"
            c = m.server_content
            if c is None:
                continue
            if c.input_transcription and c.input_transcription.text:
                state["heard"] += c.input_transcription.text
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                state["turn_open"] = True
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                state["turn_open"] = True
                state["said"] += c.output_transcription.text
                to_browser.put_nowait(("text", {"type": "said", "text": c.output_transcription.text}))
            if c.turn_complete:
                state["turn_open"] = False
                remember_turn()
                to_browser.put_nowait(("text", {"type": "turn_complete"}))
                if going_away:
                    return "go_away"
        # receive()가 한 턴을 다 내보내고 스스로 끝났다.
        return "go_away" if going_away else "turn"

    def leave_session(kept_conversation=True):
        """Gemini 연결을 떠날 때 폰 쪽을 정리한다. 답변 도중이면 턴을 닫아 버튼을 풀어 준다."""
        state["session"] = None
        if state["turn_open"]:
            state["turn_open"] = False
            remember_turn()  # 반쯤 받은 답도 들려준 만큼은 기록에 남긴다
            to_browser.put_nowait(("text", {"type": "turn_complete"}))
        to_browser.put_nowait(("text", {
            "type": "reconnecting", "kept_conversation": kept_conversation}))

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
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    opened = time.monotonic()
                    state["session"] = session
                    to_browser.put_nowait(("text", {
                        "type": "ready" if first_time else "reconnected",
                        "model": LIVE_MODEL,
                        "artwork_title": art["title_en"],
                        "session_id": visit.session_id,
                        # 핸들 없이 새로 붙었으면 앞 대화를 잃었다는 뜻이다. 폰이 안내를 바꿀 수 있게 알린다.
                        **({} if first_time else {"kept_conversation": had_handle})}))
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[live] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                # 1008 비활성, 연결 수명 초과, 핸들 거부 등.
                fails += 1
                drop_handle = had_handle and fails >= HANDLE_GIVE_UP
                print(f"[live] 세션 종료 {e.code}: {e.message}. "
                      f"다시 붙는다(핸들 {'있음' if state['handle'] else '없음'}, 연달아 실패 {fails})"
                      + (" — 핸들을 버리고 새 대화로 시작한다" if drop_handle else ""))
                if drop_handle:
                    # 핸들이 문제일 가능성이 높다(2시간 만료 등). 대화를 잃더라도 도슨트를 살린다.
                    state["handle"] = None
                leave_session(kept_conversation=not drop_handle)
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
    tasks = [asyncio.create_task(f()) for f in (browser_to_gemini, gemini_sessions, queue_to_browser)]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                print(f"[live] 중계 종료: {t.exception()!r}"[:300])
    except WebSocketDisconnect:
        pass
