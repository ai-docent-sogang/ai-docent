"""Gemini 클라이언트와 `/api/turn` 응답 생성 (담당 BE1).

`uv run python -m server.gemini_client --list-models`로 사용 가능한 모델을 조회한다.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

from .content import rank_comparisons
from .prompts import SYSTEM_INSTRUCTION

# 이미 설정된 환경 변수를 우선한다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 근거에서 벗어나는 답변을 줄이도록 낮게 설정한다.
TEMPERATURE = 0.4


class ProfileUpdate(BaseModel):
    """이번 대화에서 관람객이 새로 말한 프로필 정보. 말하지 않은 칸은 빈 값으로 온다."""

    country: str = ""
    familiar_art: list[str] = []
    depth: str = ""  # "short" 또는 "detailed"


class DocentReply(BaseModel):
    """Gemini가 반드시 이 모양의 JSON으로 답하게 한다(response_schema).

    필드를 추가·변경하면 prompts.py의 규칙 설명과 app.py의 응답, docs/api.md도 함께 고친다.
    """

    transcript: str  # 관람객이 한 말을 받아쓴 영어 문장
    artwork_id: str  # 카메라에 보이는 작품 ID. 모르면 "unknown"
    reply: str  # 이어폰으로 읽어 줄 도슨트의 답
    comparison_id: str = ""  # 답에서 실제로 사용한 비교쌍 ID. 안 썼으면 ""
    profile_update: ProfileUpdate = ProfileUpdate()


def make_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY가 없습니다. 저장소 최상위의 .env에 키를 넣으세요 (.env.example 참고).")
    return genai.Client(api_key=api_key)


def build_context(session, artworks, comparisons):
    """작품·비교쌍과 관람 세션을 JSON으로 구성한다. 추천 비교쌍을 앞에 둔다."""
    catalog = []
    for artwork_id, art in artworks.items():
        ranked = rank_comparisons(comparisons, artwork_id, session.profile, session.used_comparison_ids)
        catalog.append({
            "artwork_id": artwork_id,
            "title": art["title_en"],
            "artist": art["artist"],
            "date": art["date"],
            "medium": art["medium"],
            "facts": art["key_facts"],
            "comparisons": [{
                "comparison_id": c["comparison_id"],
                "foreign_work": f'{c["foreign_title"]} by {c["foreign_artist"]} ({c["foreign_date"]})',
                "angle": c["angle"],
                "similarities": c["similarities"],
                "differences": c["differences"],
                "already_used": c["comparison_id"] in session.used_comparison_ids,
            } for c in ranked],
        })
    state = {
        "visitor_profile": session.profile,
        "current_artwork_id": session.current_artwork_id,
        "seen_artwork_ids": session.seen_artwork_ids,
        "recent_conversation": session.history,
    }
    return "CATALOG:\n" + json.dumps(catalog, ensure_ascii=False, indent=1) + "\n\nSESSION:\n" + json.dumps(state, ensure_ascii=False, indent=1)


def ask_docent(client, model, session, artworks, comparisons, audio_wav=None, image_jpeg=None, text=None):
    """카탈로그와 관람객 입력을 한 번 보내 받아쓰기·작품 인식·답변을 요청한다."""
    parts = [types.Part.from_text(text=build_context(session, artworks, comparisons))]
    if image_jpeg:
        parts.append(types.Part.from_text(text="Current camera frame from the visitor's point of view:"))
        parts.append(types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"))
    if audio_wav:
        parts.append(types.Part.from_text(text="The visitor just said (audio). Put an exact English transcript in 'transcript':"))
        parts.append(types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"))
    if text:
        parts.append(types.Part.from_text(text=f"The visitor just said: {text}\nCopy it into 'transcript'."))

    response = client.models.generate_content(
        model=model,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=DocentReply,
            temperature=TEMPERATURE,
        ),
    )
    reply = response.parsed or DocentReply.model_validate_json(response.text)
    return sanitize_reply(reply, artworks, comparisons)


def sanitize_reply(reply, artworks, comparisons):
    """카탈로그에 없는 작품·비교쌍 ID가 세션에 기록되지 않게 검증한다."""
    if reply.artwork_id not in artworks:
        reply.artwork_id = "unknown"
    valid = {c["comparison_id"] for c in comparisons if c["artwork_id"] == reply.artwork_id}
    if reply.comparison_id not in valid:
        reply.comparison_id = ""
    return reply


if __name__ == "__main__" and "--list-models" in sys.argv:
    # 모델 목록을 순회하는 동안 클라이언트 연결을 유지한다.
    client = make_client()
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name)
