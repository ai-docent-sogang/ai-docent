"""`/api/turn` 한 번의 메타데이터를 JSON Lines 파일에 덧붙인다 (담당 BE2).

응답 시간의 평균·중앙값을 계산할 수 있게 시각, 세션 ID, 작품·비교쌍 ID,
응답 시간, 오류 유형을 기록한다. 음성·사진·대화 원문은 저장하지 않는다.
기록 디렉터리 `logs/`는 Git에서 제외한다.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "turns.jsonl"
_LOCK = Lock()


def record_turn(session_id, latency_ms, *, artwork_id=None, comparison_id=None, error=None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "artwork_id": artwork_id,
        "comparison_id": comparison_id,
        "latency_ms": latency_ms,
        "error": error,
    }
    try:
        with _LOCK:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry) + "\n")
    except OSError:
        logging.getLogger(__name__).warning("Turn metadata could not be written")
