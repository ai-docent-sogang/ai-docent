"""폰 웹앱과 Gemini를 잇는 FastAPI 서버. 음성·프레임은 요청 처리에만 쓰고 저장하지 않는다."""

import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import session as sessions
from .content import load_artworks, load_comparisons
from .gemini_client import ask_docent, make_client

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
GREETING = (
    "Hello, and welcome to the Joseon painting gallery. I'm your docent. "
    "Before we start, where are you from, and what kind of art do you enjoy back home?"
)

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

artworks = load_artworks()
comparisons = load_comparisons()
_client = None


def gemini():
    global _client
    if _client is None:
        _client = make_client()
    return _client


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/session")
def start_session():
    s = sessions.create_session()
    s.history.append({"visitor": "", "docent": GREETING})
    return {"session_id": s.session_id, "reply": GREETING}


@app.post("/api/turn")
async def turn(
    session_id: str = Form(...),
    text: str = Form(""),
    audio: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
):
    s = sessions.get_session(session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    audio_bytes = await audio.read() if audio else None
    image_bytes = await image.read() if image else None
    if not audio_bytes and not text.strip():
        raise HTTPException(400, "audio or text required")

    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise HTTPException(500, "GEMINI_MODEL is not set in docent/.env")

    started = time.perf_counter()
    reply = ask_docent(
        gemini(), model, s, artworks, comparisons,
        audio_wav=audio_bytes, image_jpeg=image_bytes, text=text.strip() or None,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    s.apply_profile_update(reply.profile_update)
    s.record_turn(reply.transcript, reply)

    art = artworks.get(reply.artwork_id)
    return {
        "transcript": reply.transcript,
        "reply": reply.reply,
        "artwork_id": reply.artwork_id,
        "artwork_title": art["title_en"] if art else "",
        "comparison_id": reply.comparison_id,
        "profile": s.profile,
        "latency_ms": latency_ms,
    }


@app.post("/api/session/{session_id}/end")
def end(session_id: str):
    sessions.end_session(session_id)
    return {"ok": True}
