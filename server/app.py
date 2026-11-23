"""AI 도슨트 HTTP·WebSocket 서버. 담당: BE1.

세션과 요청을 연결하고 콘텐츠 조회·Gemini 호출은 담당 모듈에 위임한다.
Live 라우터는 live/live.py, 요청·응답 라우터(ask·turn)는 pre_live/에 정의한다.
API 계약: docs/api.md. 음성·프레임은 처리 중에만 메모리에 둔다.
실행: uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import admin as admin_api
from . import session as sessions
from .content import load_artworks, load_comparisons
from .gemini_client import make_client
from .live import live as live_api
from .pre_live import ask as ask_api
from .pre_live import turn as turn_api
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


# Live 이전의 요청·응답 방식(server/pre_live/): 텍스트 질문(POST /api/ask)과 한 턴 대화(POST /api/turn).
# 작품 CSV와 Gemini 연결은 이 파일의 것을 함께 쓴다.
ask_api.artworks = artworks
ask_api.get_client = gemini
app.include_router(ask_api.router)

turn_api.artworks = artworks
turn_api.comparisons = comparisons
turn_api.get_client = gemini
app.include_router(turn_api.router)

# Live 중계(server/live/)는 HTTP 경로와 같은 콘텐츠 목록을 사용한다.
live_api.artworks = artworks
live_api.comparisons = comparisons
app.include_router(live_api.router)

# 운영 페이지(/admin)와 집계·켜기/끄기 API. 같은 작품 목록을 쓴다.
admin_api.artworks = artworks
app.include_router(admin_api.router)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/session")
def start_session():
    """새 관람을 시작한다. 받는 값 없음. 돌려주는 값: session_id, reply(첫 인사)."""
    s = sessions.create_session()
    s.history.append({"visitor": "", "docent": GREETING})
    return {"session_id": s.session_id, "reply": GREETING}


@app.post("/api/session/{session_id}/end")
def end(session_id: str):
    """관람을 끝내고 그 세션의 기억을 지운다. 없는 세션이어도 오류 없이 ok를 돌려준다."""
    live_api.end_visit(session_id)
    return {"ok": True}
