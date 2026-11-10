"""브라우저 ↔ 우리 서버 ↔ Gemini Live 중계 시험대(스파이크). 아직 server/app.py에 넣지 않았다.

담당: FE1 (서버에 정식으로 넣는 것은 BE1과 합의 후)
같이 보는 파일: tools/probe_live_audio.py (음성 입력 측정), docs/FE1_Live_검토.md

왜 중계가 필요한가:
    AGENTS.md는 클라이언트 코드에 API 키를 넣지 못하게 한다. 그래서 폰 브라우저가 Gemini Live에
    직접 붙을 수 없고, 우리 서버가 가운데서 음성을 넘겨주어야 한다. 이 파일은 그 경로가 실제로
    동작하는지 확인하기 위한 가장 작은 구현이다. 운영에 쓸 코드가 아니다.

없는 것(정식 구현에서 반드시 필요하다):
    - 세션 수명 관리: 음성 전용 세션은 압축 없이 15분, 연결은 약 10분 제한이다. GoAway 처리,
      contextWindowCompression, sessionResumption이 없다.
    - 여러 관람객 동시 접속, 인증, 끊김 복구, 작품 변경(다른 작품으로 이동).
    - 마이크 음성이 답변 음성을 되받는 문제(에코) 처리.

설치: uv sync --extra live
실행:
    PYTHONPATH=. uv run uvicorn --app-dir tools live_relay_spike:app --port 8013
    PYTHONPATH=. uv run python tools/fake_browser_live.py /tmp/q16k.wav KHD_SEODANG

주고받는 형식(정식 구현 때 docs/api.md에 적고 BE1·FE2와 합의한다):
    브라우저 → 서버: 첫 메시지 {"artwork_id": "..."} / 이후 16kHz PCM 바이트 / {"type":"audio_end"}
    서버 → 브라우저: {"type":"ready"|"heard"|"said"|"turn_complete"|"error"} / 24kHz PCM 바이트
"""
import asyncio, json, os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.genai import types
from server.ask import build_artwork_context
from server.content import load_artworks
from server.gemini_client import make_client
from server.prompts import ASK_INSTRUCTION

app = FastAPI()
artworks = load_artworks()
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
    )
    client = make_client()
    async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
        await ws.send_text(json.dumps({"type": "ready", "model": LIVE_MODEL,
                                       "artwork_title": art["title_en"]}))

        async def browser_to_gemini():
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:           # 폰 마이크 PCM 16kHz
                    await session.send_realtime_input(
                        audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                elif msg.get("text"):
                    if json.loads(msg["text"]).get("type") == "audio_end":
                        await session.send_realtime_input(audio_stream_end=True)

        async def gemini_to_browser():
            async for m in session.receive():
                c = m.server_content
                if c is None:
                    continue
                if c.input_transcription and c.input_transcription.text:
                    await ws.send_text(json.dumps({"type": "heard", "text": c.input_transcription.text}))
                if c.model_turn:
                    for part in c.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await ws.send_bytes(part.inline_data.data)   # 24kHz PCM 그대로
                if c.output_transcription and c.output_transcription.text:
                    await ws.send_text(json.dumps({"type": "said", "text": c.output_transcription.text}))
                if c.turn_complete:
                    await ws.send_text(json.dumps({"type": "turn_complete"}))

        try:
            await asyncio.gather(browser_to_gemini(), gemini_to_browser())
        except WebSocketDisconnect:
            pass
