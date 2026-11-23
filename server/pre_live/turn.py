"""요청·응답 방식의 대화 API (`POST /api/turn`, 담당 BE1).

Live 이전의 방식이다. 관람객의 말(또는 글)과 카메라 사진 한 장을 보내면 한 번에 답한다.
형식은 `docs/api.md` 참고. 세션 시작·종료(`/api/session`)는 Live와 함께 쓰므로 `server/app.py`에 있다.
"""

import os
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import session as sessions
from .docent_reply import ask_docent

router = APIRouter()

# app.py에서 읽은 작품·비교 목록과 Gemini 연결을 공유한다.
artworks = {}
comparisons = []
get_client = None


@router.post("/api/turn")
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
        get_client(), model, s, artworks, comparisons,
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
