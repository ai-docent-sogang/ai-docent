"""작품 ID와 질문 텍스트를 받아 도슨트 답변 텍스트를 돌려주는 API (텍스트 전용).

담당: BE1
같이 보는 파일: docs/api.md (POST /api/ask 형식), app.py (이 라우터를 등록), content.py (작품 CSV),
              prompts.py (도슨트 규칙)

/api/turn과 다른 점: 음성·사진을 받지 않는다. 받아쓰기는 FE1의 브라우저 음성 인식이, 작품 ID는
FE1(또는 작품 인식 단계)이 정해서 보낸다. 그래서 Gemini에는 그 작품 한 점의 자료만 보내고,
보내는 양이 적어 /api/turn보다 빠를 것으로 기대한다(응답의 latency_ms로 확인).

임시 답변 모드: .env에 ASK_MOCK=1을 넣으면 Gemini를 부르지 않고 고정 답변을 돌려준다.
FE1이 서버 연결과 화면·음성 흐름을 먼저 만들 때 쓴다. API 키가 없어도 동작한다.
"""

import os
import time

from fastapi import APIRouter, HTTPException
from google.genai import types
from pydantic import BaseModel

from .prompts import ASK_INSTRUCTION

router = APIRouter()

# app.py가 서버를 켤 때 채워 준다(작품 CSV, Gemini 연결 함수). 같은 CSV를 두 번 읽지 않기 위함.
artworks = {}
get_client = None

# 자료가 없거나 Gemini가 실패했을 때 관람객에게 읽어 줄 안전한 문장
FALLBACK_NO_ARTWORK = "I'm sorry, I don't have information about this painting yet. Could you tell me which painting you are looking at?"
FALLBACK_ERROR = "Sorry, I need a moment. Could you ask me again?"


class AskRequest(BaseModel):
    artwork_id: str  # data/artworks.csv의 artwork_id (예: "KHD_SSIREUM")
    question: str  # 관람객의 질문(영어 텍스트)


class AskResponse(BaseModel):
    answer: str  # 화면에 표시하고 음성으로 읽어 줄 답변
    artwork_id: str
    artwork_title: str  # 작품 영문 제목. 모르는 작품이면 ""
    status: str  # "ok" | "mock" | "no_artwork" | "error"
    source_url: str  # 답변 근거 자료의 출처(e뮤지엄 페이지). 없으면 ""
    latency_ms: int  # 서버 안에서 답변을 만드는 데 걸린 시간(밀리초)
    model: str = ""  # 실제로 답한 Gemini 모델. 임시 답변·실패면 ""


def build_artwork_context(art):
    """작품 한 점의 확인된 사실(key_facts)만 Gemini가 읽을 글로 만든다."""
    facts = "\n".join(f"- {fact}" for fact in art["key_facts"])
    return (
        f"ARTWORK: {art['title_en']}\n"
        f"Artist: {art['artist']}\nDate: {art['date']}\nMedium: {art['medium']}\n"
        f"FACTS (the only facts you may use):\n{facts}"
    )


# 첫 모델이 과부하(503)·사용 불가(404)·시간 초과면 다음 모델로 넘어간다. .env의 GEMINI_MODEL이 맨 앞.
# 바꾸려면 .env에 ASK_FALLBACK_MODELS=모델1,모델2 로 적는다.
DEFAULT_FALLBACK_MODELS = "gemini-flash-latest,gemini-3.5-flash,gemini-3.1-flash-lite"
# 모델 하나에 기다리는 최대 시간(밀리초). 관람객이 무한정 기다리지 않게 짧게 두고, 자동 재시도는 끈다.
PER_MODEL_TIMEOUT_MS = 12000


def candidate_models():
    """시도할 모델 순서: GEMINI_MODEL → ASK_FALLBACK_MODELS (중복 제거)."""
    names = [os.environ.get("GEMINI_MODEL", "")]
    names += os.environ.get("ASK_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS).split(",")
    seen = []
    for name in (n.strip() for n in names):
        if name and name not in seen:
            seen.append(name)
    return seen


def generate_answer(art, question):
    """Gemini에 작품 자료와 질문을 보내 (답변 텍스트, 답한 모델 이름)을 받는다. 모두 실패하면 마지막 오류를 올린다."""
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
            raise  # API 키 없음: 다른 모델로 바꿔도 소용없다
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
    except (Exception, SystemExit) as e:  # 모든 모델 실패, 키·모델 설정 문제 등(키가 없으면 SystemExit)
        print(f"[/api/ask] Gemini error: {e!r}"[:300])  # 서버 터미널에서 원인 확인용
        return respond(FALLBACK_ERROR, "error")
    return respond(answer, "ok", model)
