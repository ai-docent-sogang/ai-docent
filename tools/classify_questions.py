"""관람객 질문을 유형 라벨로 자동 분류하고, 사람이 붙인 라벨과 얼마나 맞는지 잰다.

담당: FE1
같이 보는 파일: docs/FE1/FE1_관람분석_측정계획.md (라벨을 어디에 쓰는지),
              docs/FE1/FE1_관람분석_측정계획.md 4장 (라벨 목록과 BE1·FE3 경계),
              data/eval/question_labels_2026-11-17.csv (사람이 붙인 라벨)

무엇을 하고 무엇을 하지 않는가:
  - 한다: 질문 텍스트 → 유형 라벨(fact·meaning·context·technique·comparison·navigation·other·unknown).
    질문 텍스트만 보고 판정할 수 있는 일이다.
  - 하지 않는다: 답했는지 못 했는지(answered·no_source) 판정. 11/14에 답변 본문으로 성공·실패를
    판정하는 것을 만들어 봤다가 폐기했다. 음성이 한 조각이라도 오면 성공으로 세어서,
    "자료가 없어 확인이 필요합니다"라는 답까지 성공으로 집계됐다. 근거가 있었는지는 답을 만든
    쪽만 안다. outcome은 BE1 응답이나 사람 기록에서 받는다.

정답 없이 쓰지 않는다:
  분류기 혼자서는 맞는지 알 수 없다. 사람이 붙인 라벨과 비교해 일치율을 재고, 어긋난 질문을
  그대로 보여준다. 애매한 질문(ambiguous=1)은 따로 집계한다. 두 사람이 봐도 갈리는 질문을
  분류기 탓으로 돌리지 않기 위해서다.

읽는 사람이 속지 않게:
  이 도구로 잰 일치율은 '질문을 쓴 사람이 붙인 라벨'과의 일치율이다. FE3가 촬영 기록을
  독립적으로 분류한 결과와 비교해야 실제 성능이 나온다.

실행:
    PYTHONPATH=. uv run python tools/classify_questions.py
    PYTHONPATH=. uv run python tools/classify_questions.py --repeats 2   # 같은 질문을 두 번 물어 흔들림 확인
"""
import argparse
import csv
import importlib.metadata
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.genai import types
from pydantic import BaseModel

from server.gemini_client import make_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip('"')

LABELS = ["fact", "meaning", "context", "technique", "comparison", "navigation", "request", "other", "unknown"]

# 라벨의 뜻을 한 줄씩 적는다. 사람과 모델이 같은 기준을 보게 하려고 정의를 한곳에 둔다.
LABEL_GUIDE = """fact: asks for a verifiable attribute of the work (artist, date, size, designation, where it is kept).
meaning: asks what something in the picture means or symbolises, or what is happening in the scene.
context: asks why or for whom the work was made, its historical background, use, or the artist's situation.
technique: asks how it was made: brushwork, pigments, ink handling, composition method, state of preservation.
comparison: asks to compare this work with another work, artist, period, or tradition.
navigation: asks about museum logistics or rules: where something is, opening hours, photography, how to use the app.
request: asks the guide to change how it speaks rather than for new information: shorter, more detail, repeat, slower, another language.
other: a clear question that none of the labels above fit.
unknown: not a question, unintelligible, or impossible to classify."""

INSTRUCTION = f"""You label visitor questions asked to a museum audio guide about Korean paintings.

Return exactly one label from this list:
{LABEL_GUIDE}

Rules:
- Label by what the visitor is asking for, not by the subject of the painting.
- A question may touch several areas. Choose the one the visitor most directly asks for.
- Questions may be in English or Korean. The label is the same either way.
- Do not answer the question. Only label it."""


class Labelled(BaseModel):
    label: str
    confidence: str  # high, medium, low


def classify(client, question):
    """질문 하나를 보내 라벨을 받는다. 온도 0으로 같은 입력에 같은 답이 나오게 한다."""
    response = client.models.generate_content(
        model=MODEL,
        contents=f"Visitor question: {question}",
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCTION,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=Labelled,
        ))
    out = json.loads(response.text)
    label = out.get("label", "").strip()
    return (label if label in LABELS else "unknown"), out.get("confidence", "")


def read_gold(path):
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if not rows:
        raise SystemExit(f"{path.relative_to(ROOT)}에 행이 없습니다.")
    for row in rows:
        if row["gold_label"] not in LABELS:
            raise SystemExit(f"{row['question_id']}의 gold_label '{row['gold_label']}'은 목록에 없습니다.")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", type=Path, default=ROOT / "data/eval/question_labels_2026-11-17.csv")
    parser.add_argument("--repeats", type=int, default=1, help="같은 질문을 몇 번 물을지. 2 이상이면 흔들림을 본다")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows = read_gold(args.gold)
    client = make_client()
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "sdk": importlib.metadata.version("google-genai"),
        "temperature": 0.0,
        "gold_file": str(args.gold.relative_to(ROOT)),
        "repeats": args.repeats,
        "note": "일치율은 질문을 쓴 사람이 붙인 라벨과의 일치율이다. 독립 분류와 비교해야 실제 성능이 나온다.",
        "rows": [],
    }
    for row in rows:
        predictions = [classify(client, row["question"]) for _ in range(args.repeats)]
        labels = [p[0] for p in predictions]
        record = {
            "question_id": row["question_id"],
            "question": row["question"],
            "lang": row.get("lang", ""),
            "gold": row["gold_label"],
            "predicted": labels[0],
            "all_predictions": labels,
            "stable": len(set(labels)) == 1,
            "confidence": predictions[0][1],
            "ambiguous": row.get("ambiguous", "0") == "1",
            "agree": labels[0] == row["gold_label"],
        }
        result["rows"].append(record)
        mark = "O" if record["agree"] else "X"
        flags = ("" if record["stable"] else " 흔들림" + str(labels)) + (" (애매)" if record["ambiguous"] else "")
        print(f"{mark} {record['question_id']} [{record['lang']}] 사람={record['gold']:<10} "
              f"모델={record['predicted']:<10}{flags}  {record['question'][:52]}")

    clear = [r for r in result["rows"] if not r["ambiguous"]]
    vague = [r for r in result["rows"] if r["ambiguous"]]
    print()
    print(f"분명한 질문 일치 {sum(r['agree'] for r in clear)}/{len(clear)}"
          + (f" ({sum(r['agree'] for r in clear) / len(clear):.0%})" if clear else ""))
    if vague:
        print(f"애매한 질문 일치 {sum(r['agree'] for r in vague)}/{len(vague)} — 사람끼리도 갈릴 수 있는 질문이다")
    if args.repeats > 1:
        unstable = [r["question_id"] for r in result["rows"] if not r["stable"]]
        print(f"같은 질문 {args.repeats}회에서 답이 바뀐 질문: {len(unstable)}건 {unstable}")

    wrong = [r for r in result["rows"] if not r["agree"]]
    if wrong:
        print("\n어긋난 질문:")
        pairs = Counter((r["gold"], r["predicted"]) for r in wrong)
        for (gold, pred), n in pairs.most_common():
            print(f"  사람 {gold} → 모델 {pred}: {n}건")
        for r in wrong:
            print(f"  [{r['question_id']}] {r['question']}")
            print(f"      사람={r['gold']} 모델={r['predicted']} 애매={'예' if r['ambiguous'] else '아니오'}")

    by_label = defaultdict(lambda: [0, 0])
    for r in result["rows"]:
        by_label[r["gold"]][1] += 1
        by_label[r["gold"]][0] += r["agree"]
    print("\n사람이 붙인 라벨별 일치:")
    for label in LABELS:
        if by_label[label][1]:
            print(f"  {label:<11} {by_label[label][0]}/{by_label[label][1]}")

    stamp = datetime.now().strftime("%Y-%m-%d")
    out = args.out or ROOT / f"data/eval/question_label_agreement_{stamp}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n기록: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    print("이 일치율을 분류기 성능으로 발표하지 않는다. FE3의 독립 분류와 비교한 뒤에 쓴다.")


if __name__ == "__main__":
    main()
