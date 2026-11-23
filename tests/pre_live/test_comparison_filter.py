"""검증 안 된 비교쌍이 /api/turn 경로에서도 후보에 오르지 않는지 본다 (server/pre_live/docent_reply.py).

담당: FE1. Live 실패 때 돌아오는 안전망이라 Live와 같은 기준(verified만)을 지켜야 한다.
실행: PYTHONPATH=. uv run python tests/pre_live/test_comparison_filter.py
Gemini를 부르지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import server.session as sessions  # noqa: E402
from server.content import load_artworks, load_comparisons, verified_comparisons  # noqa: E402
from server.pre_live import docent_reply  # noqa: E402

artworks, comparisons = load_artworks(), load_comparisons()
failures = []


def check(name, ok, detail=""):
    print(("  통과 · " if ok else "  실패 · ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


print("1. verified만 남긴다")
sample = [{"comparison_id": "A", "verification_status": "verified"},
          {"comparison_id": "B", "verification_status": " Verified "},
          {"comparison_id": "C", "verification_status": "needs_check"},
          {"comparison_id": "D"}]
check("검증된 것만(대소문자·공백 무시)", [c["comparison_id"] for c in verified_comparisons(sample)] == ["A", "B"])

print("2. /api/turn의 후보에 검증 안 된 쌍이 없다")
seen = {}
real_build = docent_reply.build_context
docent_reply.build_context = lambda s, a, c: seen.setdefault("ids", [x["comparison_id"] for x in c]) and "ctx"
art = next(iter(artworks))
unverified = {**comparisons[0], "comparison_id": "C_UNVERIFIED_TEST", "verification_status": "needs_check",
              "artwork_id": art}


class Stop(Exception):
    pass


class Client:
    class models:
        @staticmethod
        def generate_content(**kw):
            raise Stop


try:
    docent_reply.ask_docent(Client(), "m", sessions.create_session(), artworks, comparisons + [unverified],
                            text="hi")
except Stop:
    pass
finally:
    docent_reply.build_context = real_build
check("목록에 넣은 미검증 쌍이 모델에 가지 않는다", "ids" in seen and "C_UNVERIFIED_TEST" not in seen["ids"], str(seen)[:80])
check("검증된 쌍은 그대로 간다", len(seen.get("ids", [])) == len(verified_comparisons(comparisons)), str(len(seen.get("ids", []))))

print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("비교쌍 필터 시험 전부 통과")
