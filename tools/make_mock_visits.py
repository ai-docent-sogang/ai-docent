"""운영 화면(/admin)을 채워 보기 위한 가짜 관람 기록을 만든다 (담당 FE1).

실제 관람이 아니다. 기록의 source_kind는 `mock`이고, 운영 화면은 자료 종류를 하나씩만 보므로
실제 기록(team_rehearsal 등)과 섞이지 않는다. 숫자는 난수(seed 고정)라서 해석하지 않는다.
작품 체류 구간과 비관심 질문은 만들지 않으므로 "인식 구간 0초", "관심 100%"는 가짜 자료의 한계다.

실행:
    PYTHONPATH=. uv run python -m tools.make_mock_visits            # logs/mock/ 에 24건
    PYTHONPATH=. uv run python -m tools.make_mock_visits --visits 50 --out /tmp/mock
보기:
    LIVE_VISIT_DIR=logs/mock uv run python -m uvicorn server.app:app --port 8000
    → /admin 에서 자료를 "가짜 자료 (mock)"로 고르고 새로고침한다.

기본 출력 폴더 logs/mock/은 실제 기록 폴더(logs/) 안의 하위 폴더라서 서버가 실제 기록으로 읽지 않는다
(visit_stats는 logs/visits-*.jsonl만 읽는다). logs/는 Git에서 제외한다.
"""
import argparse
import os
import random
from pathlib import Path

ARTWORKS = ["KHD_SSIREUM", "JS_INWANG", "SSD_CHOCHUNG", "KHD_SEODANG", "SYB_BABY", "KJH_SEHAN", "KHD_CHUSEONG"]
COMPARISON_OF = {"KHD_SSIREUM": "C_KHD_BRUEGEL", "JS_INWANG": "C_INWANG_CEZANNE"}
LABELS = ["fact", "artist", "meaning", "context", "technique", "comparison", "navigation", "request", "other", "unknown"]
LABEL_WEIGHTS = [5, 3, 4, 2, 2, 3, 1, 1, 1, 3]
OUTCOMES = ["answered"] * 7 + ["no_source", "out_of_scope"]
END_REASONS = ["visit_ended"] * 8 + ["expired"] * 2
QUALITY_ISSUES = ["reconnect", "resumed", "interrupted", "phone_closed", "replaced"]


def make(out, visits, seed):
    os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_SOURCE_KIND="mock", LIVE_VISIT_DIR=str(out))
    from server import visit_log   # 환경 변수를 정한 뒤에 부른다

    rng = random.Random(seed)
    for _ in range(visits):
        log = visit_log.start(mode="handsfree", model="gemini-3.8-live", voice="Kore")
        path = rng.sample(ARTWORKS, rng.randint(1, 4))
        if rng.random() < 0.3:
            path.append(path[0])
        for art in path:
            log.event("artwork_identified", artwork_id=art, via="function")
            for _ in range(rng.randint(1, 4)):
                label = rng.choices(LABELS, LABEL_WEIGHTS)[0]
                grounded = label not in ("unknown", "other")
                log.event("question", artwork_id=art, channel=rng.choice(["voice"] * 5 + ["text"]), label=label,
                          outcome=rng.choice(OUTCOMES) if grounded else "unknown", grounded=grounded,
                          first_audio_ms=rng.choice([-1] + [rng.randint(900, 2800) for _ in range(9)]))
                if label == "comparison" and art in COMPARISON_OF:
                    log.event("comparison", artwork_id=art, comparison_id=COMPARISON_OF[art], via="function")
            log.event("usage", artwork_id=art, input_audio=rng.randint(500, 3000), input_image=rng.randint(300, 1500),
                      input_text=rng.randint(20, 200), output_audio=rng.randint(400, 2500),
                      total=rng.randint(1500, 7000))
        for issue in rng.choices(QUALITY_ISSUES, k=rng.randint(0, 3)):
            log.event("quality", issue=issue)
        log.end(reason=rng.choice(END_REASONS))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="logs/mock", help="기록을 쓸 폴더 (기본 logs/mock)")
    parser.add_argument("--visits", type=int, default=24, help="만들 관람 수 (기본 24)")
    parser.add_argument("--seed", type=int, default=7, help="난수 씨앗 (같으면 같은 모양)")
    args = parser.parse_args()
    out = Path(args.out)
    make(out, args.visits, args.seed)
    print(f"가짜 관람 {args.visits}건을 {out}/에 썼다. 자료 종류는 mock이다.")
