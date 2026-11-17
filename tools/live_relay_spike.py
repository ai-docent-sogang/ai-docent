"""브라우저 ↔ 우리 서버 ↔ Gemini Live 중계 시험대(스파이크). 아직 server/app.py에 넣지 않았다.

담당: FE1 (서버에 정식으로 넣는 것은 BE1과 합의 후)
같이 보는 파일: tools/probe_live_audio.py (음성 입력 측정), docs/FE1_Live_검토.md

왜 중계가 필요한가:
    AGENTS.md는 클라이언트 코드에 API 키를 넣지 못하게 한다. 그래서 폰 브라우저가 Gemini Live에
    직접 붙을 수 없고, 우리 서버가 가운데서 음성을 넘겨주어야 한다. 이 파일은 그 경로가 실제로
    동작하는지 확인하기 위한 가장 작은 구현이다. 운영에 쓸 코드가 아니다.

알아 둘 것:
    - Gemini를 읽는 일과 폰으로 보내는 일을 큐로 떼어 놓았다. 붙여 두면 폰이 느릴 때 Gemini 연결이
      keepalive ping timeout으로 끊긴다(11/11 아이폰 시험에서 실제로 끊겼다).

세션 수명(공식 문서 확인, 2026-11-14 · aistudio.google.com/docs/live-api/session-management):
    - 압축이 없으면 음성 전용 세션은 15분, 음성+영상은 2분에서 끝난다. contextWindowCompression을
      켜면 "무제한"으로 늘어난다고 적혀 있다. 그래서 켜 둔다(아래 config).
    - 연결 하나의 수명은 그와 별개로 "약 10분"이고, 연결이 끝나면 세션도 끝난다. 그래서 세션을
      여러 연결에 걸쳐 잇는 sessionResumption이 필요하다.
    - 연결이 곧 닫히기 전에 GoAway가 오고 남은 시간(timeLeft)이 함께 온다. 문서는 미리 오는
      시간을 숫자로 밝히지 않는다. 그래서 '몇 초 전에 온다'고 가정하지 않고, 받는 즉시 옮긴다.
    - 재개 핸들은 "마지막 세션 종료 뒤 2시간" 유효하다. 더 지나면 핸들이 거부될 수 있으므로
      거듭 실패하면 핸들을 버리고 새 대화로 다시 시작한다(대화 내용은 잃는다).

없는 것(정식 구현에서 반드시 필요하다):
    - 여러 관람객 동시 접속, 인증, 작품 변경(다른 작품으로 이동).
    - 마이크 음성이 답변 음성을 되받는 문제(에코) 처리.
    - 10분·15분을 넘는 실제 관람 길이의 실기기 확인(아래 처리는 모의 시험까지만 확인했다).

설치: uv sync --extra live
실행:
    PYTHONPATH=. uv run uvicorn --app-dir tools live_relay_spike:app --port 8013
    PYTHONPATH=. uv run python tools/fake_browser_live.py /tmp/q16k.wav KHD_SEODANG

아이폰으로 시험할 때는 이 서버를 켜고 HTTPS 터널 주소의 /live 를 Safari에서 연다
(static/live_test.html. 마이크는 HTTPS에서만 열린다. README의 Cloudflare 터널 참고).

주고받는 형식(정식 구현 때 docs/api.md에 적고 BE1·FE2와 합의한다):
    브라우저 → 서버: 첫 메시지 {"artwork_id": "..."}
                     버튼 누름 {"type":"speech_start"} → 16kHz PCM 바이트 → 뗌 {"type":"speech_end"}
    서버 → 브라우저: {"type":"ready"|"heard"|"said"|"turn_complete"|"error"} / 24kHz PCM 바이트
"""
import asyncio, json, os, time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.genai import types
from google.genai.errors import APIError
from server.ask import build_artwork_context
from server.content import load_artworks
from server.gemini_client import make_client
from server.prompts import ASK_INSTRUCTION

app = FastAPI()
artworks = load_artworks()

# 시험 페이지를 이 서버가 함께 내려준다. 운영 서버(server/app.py)는 건드리지 않는다.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/live")
def live_test_page():
    return FileResponse(STATIC_DIR / "live_test.html")
LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")

# 말의 시작·끝에 붙이는 무음 길이(밀리초)와 그 PCM.
#
# 왜 필요한가(11/11 억양 60발화 측정에서 4건이 첫 단어나 끝 단어를 1개 놓쳤다):
#   자동 음성 감지를 끈 수동 VAD에는 말 앞의 여유 버퍼와 침묵 허용이 없다. 공식 문서도
#   activityStart 전에 소리를 조금 보내라고 안내한다. 경계에 바로 말이 붙으면 잘린다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음


# 핸들을 가지고 연달아 이만큼 실패하면 핸들이 거부된다고 보고 버린다(재개 핸들은 마지막 세션
# 종료 뒤 2시간까지만 유효하다). 대화 내용을 잃지만 도슨트는 계속 쓸 수 있다.
HANDLE_GIVE_UP = 3
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)


async def send_silence(session):
    """말의 경계에 무음을 넣어 첫 단어·끝 단어가 잘리지 않게 한다."""
    await session.send_realtime_input(
        audio=types.Blob(data=SILENCE_PCM, mime_type="audio/pcm;rate=16000"))

@app.websocket("/ws/live")
async def live(ws: WebSocket):
    await ws.accept()
    first = json.loads(await ws.receive_text())      # 첫 메시지: 어느 작품인지
    art = artworks.get(first.get("artwork_id"))
    if art is None:
        await ws.send_text(json.dumps({"type": "error", "message": "unknown artwork"}))
        await ws.close(); return

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=f"{ASK_INSTRUCTION}\n\n{build_artwork_context(art)}",
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # 자동 음성 감지(VAD)를 끄고 말의 시작·끝을 우리가 알려 준다.
        #
        # 왜(11/11 아이폰 시험에서 두 번째 질문부터 답이 오지 않았다):
        #   기본값은 모델이 '끊기지 않는' 음성 흐름을 들으면서 침묵으로 말의 끝을 판단한다. 그런데
        #   우리 화면은 버튼을 누르는 동안만 소리를 보내므로 침묵 자체가 전달되지 않는다. 그래서
        #   모델이 말이 끝났는지 알 수 없다. 공식 문서는 이런 누르고 말하기 방식에는 자동 감지를 끄고
        #   activityStart·activityEnd로 경계를 알려 주라고 안내한다(그 모드에서는 audioStreamEnd를
        #   보내지 않는다). 처음에는 둘을 섞어 써서 첫 턴만 우연히 동작했다.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        ),
        # 끊겼을 때 대화 내용을 유지한 채 다시 붙기 위한 핸들을 받아 둔다.
        session_resumption=types.SessionResumptionConfig(),
        # 음성 전용 세션의 15분 제한을 없앤다. 공식 문서는 이 설정으로 세션을 "무제한"으로
        # 늘린다고 안내한다. 오래된 대화를 창 밖으로 밀어내는 방식(sliding window)이다.
        #
        # 값을 비워 두는 이유: 문서의 예시가 기본값(SlidingWindow())만 쓰고, 트리거 토큰 수와
        # 남길 토큰 수에 권장값을 주지 않는다. 우리가 측정한 값도 없으므로 숫자를 지어내지 않고
        # 서버 기본값에 맡긴다. 긴 관람에서 답변이 앞 대화를 잊는 것이 문제가 되면 그때 측정해서
        # trigger_tokens·target_tokens를 정한다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )
    client = make_client()

    # 지금 연결된 Live 세션과 재개 핸들. 재연결하면 session만 바뀌고 폰과의 연결은 그대로 유지한다.
    #
    # 왜 재연결이 필요한가(11/11 아이폰 시험 L09에서 2분 뒤 끊김):
    #   버튼을 누를 때만 소리를 보내므로 질문 사이에는 입력이 없다. 그러면 Gemini가 2분쯤 뒤
    #   "1008 Session closed due to client inactivity"로 세션을 닫는다. 폰에는 WebSocket이
    #   code 1006으로 끊긴 것처럼 보인다.
    #   소리를 계속 보내면(침묵까지) 끊기지 않지만, 관람 내내 마이크 소리를 전부 올리게 되므로
    #   AGENTS.md(음성은 처리에만 사용)와 요금 면에서 택하지 않았다. 대신 끊기면 다시 붙는다.
    #   음성 전용 세션 15분·연결 약 10분 제한에도 같은 처리가 필요하다.
    #   turn_open: 답변을 내보내는 중인지. 연결이 답변 도중에 옮겨 가면 폰은 turn_complete를
    #   받지 못해 버튼이 잠긴 채로 남는다. 그래서 옮기기 전에 턴을 닫아 준다.
    state = {"session": None, "handle": None, "turn_open": False}

    # 폰으로 보낼 것을 담아 두는 줄. Gemini를 읽는 일과 폰으로 보내는 일을 떼어 놓는다.
    # 붙여 두면 폰 전송이 느릴 때 Gemini 쪽 소켓을 읽지 못해 연결이 위험해진다.
    to_browser = asyncio.Queue()

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
                print(f"[relay] 보내기 실패(재연결 대기): {e!r}"[:200])
                state["session"] = None

    async def read_one_turn(session):
        """한 턴을 읽는다. 돌려주는 값은 왜 끝났는지다: "turn"(답변 끝) 또는 "go_away"(연결 교체).

        GoAway를 받은 뒤에도 답변이 나오는 중이면 끝까지 읽고 나서 옮긴다. 남은 시간을 문서가
        숫자로 밝히지 않으므로 '아직 여유가 있다'고 믿고 기다리지는 않는다. 턴이 끝나거나
        연결이 먼저 닫히면(APIError) 어느 쪽이든 바깥에서 다시 붙는다.
        """
        going_away = False
        async for m in session.receive():
            if m.session_resumption_update and m.session_resumption_update.new_handle:
                # 다시 붙을 때 쓸 핸들. 올 때마다 최신으로 바꿔 둔다.
                #
                # resumable이 꺼진 업데이트는 그 시점으로 되돌릴 수 없다는 뜻이므로 받지 않는다.
                # 그대로 덮어쓰면 거부되는 핸들로 바꿔 버릴 수 있다(공식 문서: resumable이 설정되고
                # 새 핸들이 온 업데이트를 저장하라).
                if m.session_resumption_update.resumable is not False:
                    state["handle"] = m.session_resumption_update.new_handle
            if m.go_away:
                # 연결이 곧 닫힌다는 예고(약 10분 수명). 이때 그냥 계속 읽으면 연결이 ABORTED로
                # 끊기고 그 턴의 답이 잘린다. 그래서 예고를 받으면 우리가 먼저 옮긴다.
                print(f"[relay] GoAway: 남은 시간 {m.go_away.time_left}"
                      f"{' (답변 중 — 턴을 끝내고 옮긴다)' if state['turn_open'] else ''}")
                going_away = True
                if not state["turn_open"]:
                    return "go_away"
            c = m.server_content
            if c is None:
                continue
            if c.input_transcription and c.input_transcription.text:
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                state["turn_open"] = True
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                state["turn_open"] = True
                to_browser.put_nowait(("text", {"type": "said", "text": c.output_transcription.text}))
            if c.turn_complete:
                state["turn_open"] = False
                to_browser.put_nowait(("text", {"type": "turn_complete"}))
                if going_away:
                    return "go_away"
        # receive()가 한 턴을 다 내보내고 스스로 끝났다.
        return "go_away" if going_away else "turn"

    def leave_session(kept_conversation=True):
        """Gemini 연결을 떠날 때 폰 쪽을 정리한다.

        답변 도중에 옮기면 폰은 turn_complete를 못 받아 버튼이 잠긴 채로 남는다. 그래서 턴을
        닫아 주고 재연결 중임을 알린다.
        """
        state["session"] = None
        if state["turn_open"]:
            state["turn_open"] = False
            to_browser.put_nowait(("text", {"type": "turn_complete"}))
        to_browser.put_nowait(("text", {
            "type": "reconnecting", "kept_conversation": kept_conversation}))

    async def gemini_sessions():
        """Live 세션을 열고, 끊기거나 연결 수명이 다하면 핸들로 다시 붙는다. 폰과의 연결은 끊지 않는다.

        session.receive()는 한 턴이 끝나면 스스로 끝나므로 안쪽에서 다시 부른다. 한 번만 돌리면
        두 번째 질문의 답이 오지 않고, 아무도 Gemini 소켓을 읽지 않아 연결이 끊긴다(11/11에 겪음).

        연결을 바꾸는 경우는 셋이다. 어느 쪽이든 폰과의 WebSocket은 그대로 두고 Gemini 쪽만 바꾼다.
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
                        "model": LIVE_MODEL, "artwork_title": art["title_en"],
                        # 핸들 없이 새로 붙었으면 앞 대화를 잃었다는 뜻이다. 폰이 안내를 바꿀 수 있게 알린다.
                        **({} if first_time else {"kept_conversation": had_handle})}))
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[relay] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                # 1008 비활성, 연결 수명 초과, 핸들 거부 등.
                fails += 1
                drop_handle = had_handle and fails >= HANDLE_GIVE_UP
                print(f"[relay] 세션 종료 {e.code}: {e.message}. "
                      f"다시 붙는다(핸들 {'있음' if state['handle'] else '없음'}, 연달아 실패 {fails})"
                      + (" — 핸들을 버리고 새 대화로 시작한다" if drop_handle else ""))
                if drop_handle:
                    # 핸들이 문제일 가능성이 높다(2시간 만료 등). 대화 내용을 잃더라도 도슨트를 살린다.
                    state["handle"] = None
                leave_session(kept_conversation=not drop_handle)
                # 쉬는 시간을 조금씩 늘린다. 붙자마자 계속 실패할 때 빈 바퀴를 돌지 않게 한다.
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
    # 왜 gather가 아닌가: gather는 폰 쪽 루프가 끝나도 나머지를 기다린다. 그러면 관람객이
    # 창을 닫은 뒤에도 Gemini 세션이 자기 수명(비활성 2분·연결 10분)까지 살아 있고, 우리는
    # 그동안 재연결을 계속한다. 관람객이 떠나면 세션도 바로 닫는다.
    tasks = [asyncio.create_task(f()) for f in (browser_to_gemini, gemini_sessions, queue_to_browser)]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                print(f"[relay] 중계 종료: {t.exception()!r}"[:300])
    except WebSocketDisconnect:
        pass
