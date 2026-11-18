"""AI 도슨트 HTTP·WebSocket 서버. 담당: BE1.

세션과 요청을 연결하고 콘텐츠 조회·Gemini 호출은 담당 모듈에 위임한다.
Live 라우터는 live.py, 텍스트 질문 라우터는 ask.py에 정의한다.
API 계약: docs/api.md. 음성·프레임은 처리 중에만 메모리에 둔다.
실행: uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ask as ask_api
from . import live as live_api
from . import session as sessions
from .content import load_artworks, load_comparisons
from .gemini_client import ask_docent, make_client
from .prompts import GREETING

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# CSV는 서버를 켤 때 한 번만 읽는다. CSV를 고쳤으면 서버를 다시 켜야 반영된다.
artworks = load_artworks()
comparisons = load_comparisons()
_client = None


def gemini():
    """Gemini 연결을 처음 필요할 때 한 번만 만든다. 키가 없어도 서버와 첫 화면은 켜지게 하기 위함이다."""
    global _client
    if _client is None:
        _client = make_client()
    return _client


# 텍스트 전용 질문·답변 API(POST /api/ask). 작품 CSV와 Gemini 연결은 이 파일의 것을 함께 쓴다.
ask_api.artworks = artworks
ask_api.get_client = gemini
app.include_router(ask_api.router)

# Live 중계는 HTTP 경로와 같은 콘텐츠 목록을 사용한다.
live_api.artworks = artworks
live_api.comparisons = comparisons
app.include_router(live_api.router)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/session")
def start_session():
    """새 관람을 시작한다. 받는 값 없음. 돌려주는 값: session_id, reply(첫 인사)."""
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
    """관람객의 말 한 번에 도슨트가 답한다. 형식은 docs/api.md 참고.

    받는 값(multipart/form-data): session_id(필수), audio(16kHz WAV) 또는 text 중 하나 이상, image(JPEG, 선택)
    오류: 404 세션 없음 / 400 음성·글 둘 다 없음 / 500 .env에 GEMINI_MODEL 없음
    """
    s = sessions.get_session(session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    audio_bytes = await audio.read() if audio else None
    image_bytes = await image.read() if image else None
    if not audio_bytes and not text.strip():
        raise HTTPException(400, "audio or text required")

    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise HTTPException(500, "GEMINI_MODEL is not set in .env")

    # latency_ms는 서버 안에서 Gemini 호출에 걸린 시간만 잰다. 전체 체감 시간은 웹앱이 따로 잰다.
    started = time.perf_counter()
    reply = ask_docent(
        gemini(), model, s, artworks, comparisons,
        audio_wav=audio_bytes, image_jpeg=image_bytes, text=text.strip() or None,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    # 답을 받은 뒤에 세션을 갱신한다: 프로필 → 본 작품·쓴 비교 → 대화 기록
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
    """관람을 끝내고 그 세션의 기억을 지운다. 없는 세션이어도 오류 없이 ok를 돌려준다."""
    live_api.end_visit(session_id)
    return {"ok": True}
