"""Live 대화의 대체 경로인 텍스트 질의 API (`POST /api/ask`, 담당 BE1).

작품 한 점의 자료로 답한다. `ASK_MOCK=1`로 API 키 없이 연동을 시험할 수 있다.
요청·응답 형식은 `docs/api.md` 참고.
"""

import os
import time

from fastapi import APIRouter, HTTPException
from google.genai import types
from pydantic import BaseModel

from ..content import build_artwork_context
from ..prompts import ASK_INSTRUCTION

router = APIRouter()

# app.py에서 읽은 작품 목록과 Gemini 클라이언트를 공유한다.
artworks = {}
get_client = None

FALLBACK_NO_ARTWORK = "I'm sorry, I don't have information about this painting yet. Could you tell me which painting you are looking at?"
FALLBACK_ERROR = "Sorry, I need a moment. Could you ask me again?"


class AskRequest(BaseModel):
    artwork_id: str
    question: str


class AskResponse(BaseModel):
    answer: str
    artwork_id: str
    artwork_title: str
    status: str  # "ok" | "mock" | "no_artwork" | "error"
    source_url: str
    latency_ms: int
    model: str = ""


DEFAULT_FALLBACK_MODELS = "gemini-flash-latest,gemini-3.5-flash,gemini-3.1-flash-lite"
PER_MODEL_TIMEOUT_MS = 12000


def candidate_models():
    """`GEMINI_MODEL` 다음에 `ASK_FALLBACK_MODELS`를 중복 없이 시도한다."""
    names = [os.environ.get("GEMINI_MODEL", "")]
    names += os.environ.get("ASK_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS).split(",")
    seen = []
    for name in (n.strip() for n in names):
        if name and name not in seen:
            seen.append(name)
    return seen


def generate_answer(art, question):
    """첫 성공 응답의 본문과 모델명을 반환한다. 모두 실패하면 마지막 오류를 올린다."""
    models = candidate_models()
    if not models:
        raise RuntimeError("GEMINI_MODEL is not set in .env")
    last_error = None
    for model in models:
        try:
            response = get_client().models.generate_content(
                model=model,
                contents=f"{build_artwork_context(art)}\n\nVISITOR QUESTION: {question}",
                config=types.GenerateContentConfig(
                    system_instruction=ASK_INSTRUCTION,
                    temperature=0.4,
                    http_options=types.HttpOptions(
                        timeout=PER_MODEL_TIMEOUT_MS,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
            answer = (response.text or "").strip()
            if answer:
                return answer, model
            last_error = RuntimeError(f"{model}: empty answer")
        except SystemExit:
            raise  # API 키 누락은 모델을 바꿔도 해결되지 않는다.
        except Exception as e:
            print(f"[/api/ask] {model} failed, trying next: {e!r}"[:300])
            last_error = e
    raise last_error


@router.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """작품 ID + 질문 → 답변. 형식은 docs/api.md 참고.

    오류: 400 질문이 비었음. 자료 없는 작품·Gemini 실패는 오류 대신 status와 안전한 안내 문장으로 답한다
    (관람객에게는 항상 읽어 줄 문장이 있어야 하므로).
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is required")

    started = time.perf_counter()
    art = artworks.get(req.artwork_id)

    def respond(answer, status, model=""):
        return AskResponse(
            model=model,
            answer=answer,
            artwork_id=req.artwork_id,
            artwork_title=art["title_en"] if art else "",
            status=status,
            source_url=art["official_url"] if art else "",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    if art is None or not art["key_facts"]:
        return respond(FALLBACK_NO_ARTWORK, "no_artwork")
    if os.environ.get("ASK_MOCK") == "1":
        return respond(f"(mock answer) You asked about {art['title_en']}: \"{question}\"", "mock")
    try:
        answer, model = generate_answer(art, question)
    except (Exception, SystemExit) as e:  # API 키 누락의 SystemExit도 안내 문장으로 처리한다.
        print(f"[/api/ask] Gemini error: {e!r}"[:300])
        return respond(FALLBACK_ERROR, "error")
    return respond(answer, "ok", model)
