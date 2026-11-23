"""`/api/turn` 응답 생성: 카탈로그와 관람객 입력을 Gemini에 한 번 보내 JSON으로 받는다 (담당 BE1).

Live 이전의 요청·응답 방식이다. Gemini 클라이언트는 `server/gemini_client.py`의 `make_client`를 쓴다.
"""

import json

from google.genai import types
from pydantic import BaseModel

from ..content import rank_comparisons
from ..prompts import SYSTEM_INSTRUCTION

# 근거에서 벗어나는 답변을 줄이도록 낮게 설정한다.
TEMPERATURE = 0.4


class ProfileUpdate(BaseModel):
    """이번 대화에서 관람객이 새로 말한 프로필 정보. 말하지 않은 칸은 빈 값으로 온다."""

    country: str = ""
    familiar_art: list[str] = []
    depth: str = ""  # "short" 또는 "detailed"


class DocentReply(BaseModel):
    """Gemini가 반드시 이 모양의 JSON으로 답하게 한다(response_schema).

    필드를 추가·변경하면 prompts.py의 규칙 설명과 pre_live/turn.py의 응답, docs/api.md도 함께 고친다.
    """

    transcript: str  # 관람객이 한 말을 받아쓴 영어 문장
    artwork_id: str  # 카메라에 보이는 작품 ID. 모르면 "unknown"
    reply: str  # 이어폰으로 읽어 줄 도슨트의 답
    comparison_id: str = ""  # 답에서 실제로 사용한 비교쌍 ID. 안 썼으면 ""
    profile_update: ProfileUpdate = ProfileUpdate()


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
