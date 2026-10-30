"""Gemini 요청-응답 방식: 음성(WAV) + 카메라 프레임(JPEG) + 세션 맥락 → 도슨트 답변(JSON)."""

import json
import os
import sys

from google import genai
from google.genai import types
from pydantic import BaseModel

from .content import rank_comparisons

SYSTEM_INSTRUCTION = """You are a friendly museum docent at the Joseon painting gallery of the National Museum of Korea.
You talk with one foreign visitor in English, through earphones. Your answers are spoken aloud.

Rules:
- Facts about artworks must come only from the CATALOG below. If the catalog does not say it, say you are not sure. Never invent dates, names, sizes, or stories.
- Identify which catalog artwork the camera image shows. If the image is unclear or not in the catalog, use artwork_id "unknown" and kindly ask which painting they are looking at.
- Personalize: use the visitor profile. When it fits the conversation, compare the current painting with ONE foreign painting from its comparison list, preferring the first one listed (it is already ranked for this visitor). Mention one similarity and one difference. Present it as a way of looking, never as historical influence.
- If the profile is still missing the visitor's country or the kind of art they know, ask about it naturally (one question at a time).
- Keep each reply to 2-4 short spoken sentences, then invite a question or point out something to look at. No lists, no markdown.
- Set comparison_id only when your reply actually uses that comparison; otherwise use "".
- Put into profile_update only what the visitor said in THIS turn (country, kinds of art they know, preferred depth "short" or "detailed")."""


class ProfileUpdate(BaseModel):
    country: str = ""
    familiar_art: list[str] = []
    depth: str = ""


class DocentReply(BaseModel):
    transcript: str
    artwork_id: str
    reply: str
    comparison_id: str = ""
    profile_update: ProfileUpdate = ProfileUpdate()


def make_client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def build_context(session, artworks, comparisons):
    """세션 상태와 콘텐츠 DB를 프롬프트용 텍스트로 만든다."""
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
            temperature=0.4,
        ),
    )
    reply = response.parsed or DocentReply.model_validate_json(response.text)
    return sanitize_reply(reply, artworks, comparisons)


def sanitize_reply(reply, artworks, comparisons):
    """모델이 카탈로그에 없는 ID를 돌려주면 버린다."""
    if reply.artwork_id not in artworks:
        reply.artwork_id = "unknown"
    valid = {c["comparison_id"] for c in comparisons if c["artwork_id"] == reply.artwork_id}
    if reply.comparison_id not in valid:
        reply.comparison_id = ""
    return reply


if __name__ == "__main__" and "--list-models" in sys.argv:
    for m in make_client().models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name)
