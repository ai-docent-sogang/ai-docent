"""Gemini에 한 번 물어보고 도슨트 답을 받아 오는 파일.

담당: BE1
같이 보는 파일: prompts.py (지시문), content.py (작품·비교쌍), session.py (관람객 기억), app.py (이 파일을 부름)

흐름: 세션 상태와 작품 목록을 글(JSON)로 만들고 → 사진·음성·글과 함께 Gemini에 보내고
→ 정해진 모양(DocentReply)의 JSON으로 답을 받고 → 목록에 없는 ID는 지운다.
받아쓰기, 작품 인식, 답변 생성을 Gemini 호출 한 번으로 처리한다(개발계획서 4장 B안).

명령어로 실행하면 이 키로 쓸 수 있는 모델 ID를 보여 준다:
    uv run python -m server.gemini_client --list-models
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

# docent/.env를 읽는다. 이미 설정된 환경 변수는 덮어쓰지 않는다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 답의 다양성. 0에 가까울수록 같은 질문에 같은 답을 하고, 높을수록 표현이 다양해지지만
# 지시를 벗어날 가능성도 커진다. 사실만 말해야 하는 도슨트라 낮게 둔다.
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
    """.env의 GEMINI_API_KEY로 Gemini 연결 객체를 만든다. 키가 없으면 안내하고 멈춘다."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY가 없습니다. docent/.env에 키를 넣으세요 (.env.example 참고).")
    return genai.Client(api_key=api_key)


def build_context(session, artworks, comparisons):
    """세션 상태와 콘텐츠 DB를 Gemini가 읽을 글로 만든다.

    CATALOG: 모든 작품의 사실(key_facts)과 비교쌍. 비교쌍은 이 관람객에게 맞는 순서로 정렬되어 있어,
             프롬프트의 "첫 번째 비교를 우선하라"는 규칙과 짝을 이룬다.
    SESSION: 프로필, 지금 보고 있는 작품, 이미 본 작품, 최근 대화.
    """
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
    """한 번의 대화(턴)를 Gemini에 보내고 DocentReply를 돌려준다.

    보내는 순서: ① 작품 목록과 세션(build_context) ② 카메라 사진 ③ 관람객의 말(음성 또는 글).
    사진과 말 앞에 짧은 설명 문장을 붙여 Gemini가 각 자료가 무엇인지 헷갈리지 않게 한다.
    음성(audio_wav)과 글(text)은 둘 중 하나만 와도 된다. 사진이 없으면 작품 인식은 대화 맥락에만 의존한다.
    """
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
            response_mime_type="application/json",  # 답을 JSON으로만 받는다
            response_schema=DocentReply,  # 그 JSON이 DocentReply 모양이어야 한다
            temperature=TEMPERATURE,
        ),
    )
    # 보통은 SDK가 response.parsed로 바꿔 준다. 비어 있으면 원문 JSON을 직접 읽는다.
    reply = response.parsed or DocentReply.model_validate_json(response.text)
    return sanitize_reply(reply, artworks, comparisons)


def sanitize_reply(reply, artworks, comparisons):
    """모델이 카탈로그에 없는 작품·비교쌍 ID를 돌려주면 버린다(지어낸 ID가 세션에 기록되지 않게)."""
    if reply.artwork_id not in artworks:
        reply.artwork_id = "unknown"
    valid = {c["comparison_id"] for c in comparisons if c["artwork_id"] == reply.artwork_id}
    if reply.comparison_id not in valid:
        reply.comparison_id = ""
    return reply


if __name__ == "__main__" and "--list-models" in sys.argv:
    # 임시 클라이언트는 목록을 다 받기 전에 정리되어 연결이 닫힐 수 있어 변수에 붙잡아 둔다.
    client = make_client()
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name)
