"""방식 비교 실험: 요청-응답(지금 방식) vs Gemini Live API(실시간 음성)를 같은 질문 10개로 비교한다.

담당: BE1 (역할 가이드 3장, 11/5–11/11 과제)
같이 보는 파일: server/ask.py (요청-응답 방식, 같은 작품 자료·지시문을 씀), docs/api.md

실행:
    uv run python -m tools.compare_modes            # 두 방식 모두
    uv run python -m tools.compare_modes --list-live  # 이 키로 쓸 수 있는 Live 모델 목록
    uv run python -m tools.compare_modes --fast --only-a  # A의 "생각 단계"를 최소로 줄여 A만 다시 잰다

공정하게 비교하려고 두 방식 모두 같은 질문 텍스트, 같은 작품 자료(key_facts), 같은 지시문(ASK_INSTRUCTION)을 쓴다.
재는 값(밀리초):
    first_ms  질문을 보낸 뒤 첫 응답 조각이 올 때까지 (A: 첫 글자, B: 첫 음성). 관람객이 "기다린다"고 느끼는 시간
    total_ms  답이 끝까지 올 때까지
    connect_ms (B만) Live 연결을 여는 데 걸린 시간. 실제 서비스에선 관람 시작 때 한 번만 연다
한계: 음성 입력은 쓰지 않는다(질문은 텍스트). A의 음성 출력은 브라우저 speechSynthesis가 맡으므로 시간에 넣지 않았다.
결과는 data/eval/mode_comparison.csv에 저장한다. answer 열을 보고 사람이 fact_ok(사실 정확)·natural(자연스러움)을 채점한다.
"""

import asyncio
import csv
import os
import statistics
import sys
import time
from pathlib import Path

from google.genai import types

from server.ask import build_artwork_context, candidate_models
from server.content import load_artworks
from server.gemini_client import make_client
from server.prompts import ASK_INSTRUCTION

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "mode_comparison.csv"

# --fast: 답하기 전에 속으로 생각하는 단계를 최소(MINIMAL)로 줄인다. 첫 응답이 빨라지는 대신 답이 단순해질 수 있다.
FAST = "--fast" in sys.argv
ONLY_A = "--only-a" in sys.argv

# Live 모델 후보. .env에 LIVE_MODEL을 적으면 그것을 먼저 쓴다. 없으면 계정 목록에서 찾는다.
LIVE_MODEL_CANDIDATES = ["gemini-3.8-live", "gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-preview-12-2025"]

# 같은 질문 10개: 작품 소개, 사실 질문, 비교 요청, CSV에 없는 질문(모른다고 해야 정답)을 섞었다.
QUESTIONS = [
    ("Q01", "KHD_SSIREUM", "What am I looking at?"),
    ("Q02", "KHD_SSIREUM", "Who painted this?"),
    ("Q03", "KHD_SSIREUM", "How much is this painting worth?"),  # CSV에 없음
    ("Q04", "KHD_SEODANG", "Why is the boy crying?"),
    ("Q05", "JS_INWANG", "Is this a real place?"),
    ("Q06", "JS_INWANG", "How big is this painting?"),
    ("Q07", "KSH_SELF", "Who is the man in this portrait?"),
    ("Q08", "KSH_SELF", "What was the painter's favorite food?"),  # CSV에 없음
    ("Q09", "KJH_SEHAN", "What is special about this painting?"),
    ("Q10", "KHD_CHUSEONG", "Can you explain it in one sentence?"),
]


def prompt_for(art, question):
    return f"{build_artwork_context(art)}\n\nVISITOR QUESTION: {question}"


def run_request_response(client, art, question):
    """A안: 지금 방식(generate_content). 스트리밍으로 받아 첫 글자 시간과 전체 시간을 잰다. 과부하면 다음 모델."""
    last_error = None
    for model in candidate_models():
        started = time.perf_counter()
        first_ms, chunks = None, []
        try:
            stream = client.models.generate_content_stream(
                model=model,
                contents=prompt_for(art, question),
                config=types.GenerateContentConfig(
                    system_instruction=ASK_INSTRUCTION,
                    temperature=0.4,
                    thinking_config=types.ThinkingConfig(thinking_level="MINIMAL") if FAST else None,
                    http_options=types.HttpOptions(timeout=12000, retry_options=types.HttpRetryOptions(attempts=1)),
                ),
            )
            for chunk in stream:
                if chunk.text:
                    if first_ms is None:
                        first_ms = ms_since(started)
                    chunks.append(chunk.text)
            return {"model": model, "first_ms": first_ms, "total_ms": ms_since(started), "answer": "".join(chunks).strip()}
        except Exception as e:
            print(f"  A {model} failed, trying next: {str(e)[:120]}")
            last_error = e
    return {"model": "", "first_ms": None, "total_ms": None, "answer": "", "error": str(last_error)[:200]}


async def run_live(client, model, art, question):
    """B안: Live API. 질문마다 연결을 새로 열어 연결 시간·첫 음성 시간·전체 시간을 잰다. 답의 글은 음성 받아쓰기로 받는다."""
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=ASK_INSTRUCTION,
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    t0 = time.perf_counter()
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            connect_ms = ms_since(t0)
            started = time.perf_counter()
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=prompt_for(art, question))]),
                turn_complete=True,
            )
            first_ms, words, audio_bytes = None, [], 0
            async for msg in session.receive():
                content = msg.server_content
                if content is None:
                    continue
                if content.model_turn:
                    for part in content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            if first_ms is None:
                                first_ms = ms_since(started)
                            audio_bytes += len(part.inline_data.data)
                if content.output_transcription and content.output_transcription.text:
                    words.append(content.output_transcription.text)
                if content.turn_complete:
                    break
            # 24kHz·16bit·모노 PCM 기준으로 음성 길이(초)를 계산한다(해설 15~30초 목표 확인용)
            return {"model": model, "connect_ms": connect_ms, "first_ms": first_ms, "total_ms": ms_since(started),
                    "answer": "".join(words).strip(), "audio_sec": round(audio_bytes / 48000, 1)}
    except Exception as e:
        return {"model": model, "connect_ms": None, "first_ms": None, "total_ms": None, "answer": "", "error": str(e)[:200]}


def live_models(client):
    """이 키로 Live(bidiGenerateContent)를 쓸 수 있는 모델 이름 목록."""
    return [m.name.removeprefix("models/") for m in client.models.list() if "bidiGenerateContent" in (m.supported_actions or [])]


def pick_live_model(client):
    if os.environ.get("LIVE_MODEL"):
        return os.environ["LIVE_MODEL"]
    available = live_models(client)
    for name in LIVE_MODEL_CANDIDATES:
        if name in available:
            return name
    return available[0] if available else ""


def ms_since(started):
    return round((time.perf_counter() - started) * 1000)


def summarize(rows, prefix):
    """성공한 답만 모아 중앙값·평균을 낸다(None은 제외)."""
    def stat(key):
        values = [r[key] for r in rows if r.get(key) is not None]
        if not values:
            return "-"
        return f"{statistics.median(values) / 1000:.1f}초 (평균 {statistics.mean(values) / 1000:.1f}초)"
    ok = sum(1 for r in rows if r.get("answer"))
    return {"방식": prefix, "성공": f"{ok}/{len(rows)}", "첫 응답(중앙값)": stat("first_ms"), "전체(중앙값)": stat("total_ms")}


def main():
    client = make_client()
    if "--list-live" in sys.argv:
        print("\n".join(live_models(client)) or "Live 모델이 없습니다")
        return

    artworks = load_artworks()
    live_model = "" if ONLY_A else pick_live_model(client)
    out_path = OUT_PATH.with_name("mode_comparison_fast.csv") if FAST else OUT_PATH
    print(f"A: 요청-응답 모델 순서 {candidate_models()}\nB: Live 모델 {live_model or '(없음)'}\n")

    rows_a, rows_b = [], []
    for qid, artwork_id, question in QUESTIONS:
        art = artworks[artwork_id]
        print(f"{qid} [{artwork_id}] {question}")
        a = run_request_response(client, art, question)
        print(f"  A {a.get('model')}: first {a.get('first_ms')}ms, total {a.get('total_ms')}ms")
        b = asyncio.run(run_live(client, live_model, art, question)) if live_model else {"error": "skipped" if ONLY_A else "no live model"}
        print(f"  B {b.get('model')}: connect {b.get('connect_ms')}ms, first {b.get('first_ms')}ms, total {b.get('total_ms')}ms {b.get('error', '')}")
        rows_a.append(a)
        rows_b.append(b)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "artwork_id", "question", "mode", "model", "connect_ms", "first_ms", "total_ms",
                    "audio_sec", "answer", "error", "fact_ok", "natural", "note"])
        for (qid, artwork_id, question), a, b in zip(QUESTIONS, rows_a, rows_b):
            for mode, r in (("A_request_response", a), ("B_live", b)):
                w.writerow([qid, artwork_id, question, mode, r.get("model", ""), r.get("connect_ms", ""), r.get("first_ms", ""),
                            r.get("total_ms", ""), r.get("audio_sec", ""), r.get("answer", ""), r.get("error", ""), "", "", ""])

    print("\n| 방식 | 성공 | 첫 응답(중앙값) | 전체(중앙값) |\n| --- | --- | --- | --- |")
    for s in (summarize(rows_a, "A 요청-응답" + (" (생각 최소)" if FAST else "")), summarize(rows_b, "B Live API")):
        print(f"| {s['방식']} | {s['성공']} | {s['첫 응답(중앙값)']} | {s['전체(중앙값)']} |")
    connects = [r["connect_ms"] for r in rows_b if r.get("connect_ms") is not None]
    if connects:
        print(f"\nB Live 연결 시간 중앙값: {statistics.median(connects) / 1000:.1f}초 (관람 시작 때 한 번만 열면 매 질문에선 빠짐)")
    print(f"\n결과 저장: {out_path}\nanswer 열을 읽고 fact_ok(O/X), natural(1~5)을 채점하세요.")


if __name__ == "__main__":
    main()
