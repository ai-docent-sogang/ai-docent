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

없는 것(정식 구현에서 반드시 필요하다):
    - 세션 수명 관리: 음성 전용 세션은 압축 없이 15분, 연결은 약 10분 제한이다. GoAway 처리,
      contextWindowCompression, sessionResumption이 없다.
    - 여러 관람객 동시 접속, 인증, 끊김 복구, 작품 변경(다른 작품으로 이동).
    - 마이크 음성이 답변 음성을 되받는 문제(에코) 처리.

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
import asyncio, json, os
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
    state = {"session": None, "handle": None}

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
                    elif kind == "speech_end":   # 버튼에서 손을 뗀 순간 → 여기서 답을 만들기 시작한다
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
            except Exception as e:
                # 세션이 막 끊긴 경우. 바깥 루프가 다시 붙을 때까지 흘려보낸다.
                print(f"[relay] 보내기 실패(재연결 대기): {e!r}"[:200])
                state["session"] = None

    async def read_one_turn(session):
        async for m in session.receive():
            if m.session_resumption_update and m.session_resumption_update.new_handle:
                # 다시 붙을 때 쓸 핸들. 올 때마다 최신으로 바꿔 둔다.
                state["handle"] = m.session_resumption_update.new_handle
            if m.go_away:
                # 연결이 곧 닫힌다는 예고. 남은 시간을 로그에 남기고 바깥 루프가 다시 붙게 한다.
                print(f"[relay] GoAway: 남은 시간 {m.go_away.time_left}")
                return
            c = m.server_content
            if c is None:
                continue
            if c.input_transcription and c.input_transcription.text:
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                to_browser.put_nowait(("text", {"type": "said", "text": c.output_transcription.text}))
            if c.turn_complete:
                to_browser.put_nowait(("text", {"type": "turn_complete"}))

    async def gemini_sessions():
        """Live 세션을 열고, 끊기면 핸들로 다시 붙는다. 폰과의 연결은 끊지 않는다.

        session.receive()는 한 턴이 끝나면 스스로 끝나므로 안쪽에서 다시 부른다. 한 번만 돌리면
        두 번째 질문의 답이 오지 않고, 아무도 Gemini 소켓을 읽지 않아 연결이 끊긴다(11/11에 겪음).
        """
        first_time = True
        while True:
            config.session_resumption = types.SessionResumptionConfig(handle=state["handle"])
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    state["session"] = session
                    to_browser.put_nowait(("text", {
                        "type": "ready" if first_time else "reconnected",
                        "model": LIVE_MODEL, "artwork_title": art["title_en"]}))
                    first_time = False
                    while True:
                        await read_one_turn(session)
            except APIError as e:
                # 1008 비활성, 연결 시간 제한 등. 핸들이 있으면 대화를 이어서 다시 붙는다.
                state["session"] = None
                print(f"[relay] 세션 종료 {e.code}: {e.message}. 다시 붙는다(핸들 {'있음' if state['handle'] else '없음'})")
                to_browser.put_nowait(("text", {"type": "reconnecting"}))
                await asyncio.sleep(0.5)

    async def queue_to_browser():
        """줄에 쌓인 것을 폰으로 보낸다. 느려도 Gemini 읽기를 막지 않는다."""
        while True:
            kind, payload = await to_browser.get()
            if kind == "bytes":
                await ws.send_bytes(payload)
            else:
                await ws.send_text(json.dumps(payload))

    try:
        await asyncio.gather(browser_to_gemini(), gemini_sessions(), queue_to_browser())
    except WebSocketDisconnect:
        pass
