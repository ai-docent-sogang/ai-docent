"""관람 기록(`logs/visits-*.jsonl`)을 읽어 운영 페이지가 쓸 숫자를 만든다 (담당 FE1).

쓰기는 `server/visit_log.py`가 하고 읽기는 이 파일이 한다. 같은 사실을 두 번 적지 않으려고
폴더는 `visit_log.log_dir()`, 자료 종류는 `visit_log.SOURCE_KINDS`, 라벨과 덩이는
`server/question_labels.py`에서 받아 쓴다.

보관 기간 정리(`visit_log.purge_old`)를 부르지 않는다. 운영 페이지를 새로고침할 때마다
기록이 지워지면 안 된다.

비율을 계산하지 않고 분자와 분모를 함께 돌려준다. `a/b (p%)` 표기와 분모 0일 때의 N/A는
화면이 맡는다(`docs/FE1/FE1_관람분석_측정계획.md` 지표 사전).
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from . import visit_log
from .question_labels import GROUPS, LABELS, OUTCOMES, group_of

# 관람 하나가 자정을 넘기면 두 파일에 걸린다. 그래서 요청 기간 양쪽으로 하루씩 더 읽는다.
EDGE_DAYS = 1
ATTRIBUTION = "visit_start의 시각이 든 날의 관람으로 센다"


def _parse_day(text: str) -> date:
    """`YYYY-MM-DD`를 날짜로 바꾼다. 형식이 틀리면 ValueError."""
    return date.fromisoformat(text)


def _file_days(first: date, last: date) -> list[date]:
    span = (last - first).days
    return [first + timedelta(days=offset) for offset in range(span + 1)]


def read_lines(folder: Path, days: list[date], source_kind: str) -> tuple[list[dict], list[str]]:
    """해당 날짜 파일들에서 요청한 자료 종류의 줄만 읽는다. 없는 파일은 조용히 넘어간다."""
    rows, files = [], []
    for day in days:
        path = folder / f"visits-{day.strftime('%Y%m%d')}.jsonl"
        if not path.exists():
            continue
        files.append(path.name)
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not text.strip():
                continue
            try:
                line = json.loads(text)
            except json.JSONDecodeError:
                rows.append({"_broken": f"{path.name}:{number}"})
                continue
            if line.get("source_kind") == source_kind:
                rows.append(line)
    return rows, files


def group_visits(rows: list[dict], first: date, last: date) -> tuple[dict[str, list[dict]], list[str]]:
    """`visit_id`로 묶고 `t` 순으로 세운다. 기간에 귀속되지 않는 묶음은 버리고 이유를 남긴다."""
    warnings = [f"깨진 줄을 건너뛰었다: {r['_broken']}" for r in rows if "_broken" in r]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if "_broken" in row:
            continue
        groups.setdefault(row.get("visit_id", ""), []).append(row)

    kept = {}
    for visit_id, lines in groups.items():
        lines.sort(key=lambda r: r.get("t", 0))
        starts = [r for r in lines if r.get("event") == "visit_start"]
        if len(starts) != 1:
            warnings.append(
                f"관람 {visit_id[:8]}: visit_start가 {len(starts)}개다. 집계에서 뺀다")
            continue
        bucket = str(starts[0].get("start_bucket") or "")
        try:
            started = _parse_day(bucket[:10])
        except ValueError:
            warnings.append(f"관람 {visit_id[:8]}: start_bucket을 읽을 수 없다({bucket!r}). 집계에서 뺀다")
            continue
        if not (first <= started <= last):
            continue          # 양쪽으로 더 읽은 날의 관람. 조용히 넘긴다
        kept[visit_id] = lines
    return kept, warnings


def dwells(rows: list[dict]) -> list[dict]:
    """작품별 인식 구간. 체류 시간이 아니다.

    특정 작품 인식부터 다른 작품 인식까지를 한 구간으로 본다. 같은 작품을 다시 보고한 것은
    같은 구간으로 이어 간다(`live_conversation.py`에 중복 방지가 없다). `artwork_unknown`은
    구간을 끊지 않는다. 서버가 그때 지금 작품을 지우지 않기 때문이다.

    마지막 구간은 `visit_end`까지다. 종료 기록이 없으면 마지막 줄까지로 보고 `open_ended`로
    표시한다. 그 값은 하한값이다.
    """
    out: list[dict] = []
    current = None
    end_t = None
    for row in rows:
        if row.get("event") == "visit_end":
            end_t = row.get("t")
        if row.get("event") != "artwork_identified":
            continue
        artwork_id = row.get("artwork_id") or ""
        if current is None:
            current = (artwork_id, row.get("t", 0))
            continue
        if artwork_id == current[0]:
            continue
        out.append({"artwork_id": current[0], "start_t": current[1],
                    "end_t": row.get("t", 0), "open_ended": False})
        current = (artwork_id, row.get("t", 0))
    if current is not None:
        last = end_t if end_t is not None else max((r.get("t", 0) for r in rows), default=current[1])
        out.append({"artwork_id": current[0], "start_t": current[1], "end_t": last,
                    "open_ended": end_t is None})
    for item in out:
        item["recognized_s"] = round(max(0.0, item["end_t"] - item["start_t"]), 1)
    return out


def _numbers(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "mean": None, "total": 0}
    return {"n": len(values), "median": round(statistics.median(values), 1),
            "mean": round(statistics.mean(values), 1), "total": round(sum(values), 1)}


def _p90(values: list[int]) -> int | None:
    """최근접 순위 p90. 표본이 10의 배수일 때 한 칸 높게 집던 버그를 고쳤다(11/19)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def summarize(visits: dict[str, list[dict]]) -> dict:
    """묶인 관람에서 작품별·전체 숫자를 만든다."""
    per: dict[str, dict] = {}
    totals = {"questions": 0, "labels": {label: 0 for label in LABELS},
              "groups": {group: 0 for group in GROUPS}, "outcomes": {name: 0 for name in OUTCOMES},
              "speech_turns": 0, "questions_unassigned": 0, "artwork_unknown": 0}
    transitions: dict[tuple[str, str], int] = {}
    sequences, durations, first_audio, unmeasured = [], [], [], 0
    quality: dict[str, int] = {}
    end_reasons: dict[str, int] = {}
    ended = 0

    def slot(artwork_id: str) -> dict:
        return per.setdefault(artwork_id, {
            "artwork_id": artwork_id, "visits_with_dwell": 0, "identifies": 0, "dwells": 0,
            "revisit_dwells": 0, "open_ended_dwells": 0, "recognized_s": [], "questions": 0,
            "speech_turns": 0,
            "labels": {label: 0 for label in LABELS}, "groups": {group: 0 for group in GROUPS},
            "outcomes": {name: 0 for name in OUTCOMES}, "comparisons": 0,
            "tokens": {"input_audio": 0, "input_image": 0, "input_text": 0, "output_audio": 0,
                       "total": 0}})

    for visit_id, rows in visits.items():
        spans = dwells(rows)
        seen: set[str] = set()
        for index, span in enumerate(spans):
            entry = slot(span["artwork_id"])
            entry["dwells"] += 1
            entry["recognized_s"].append(span["recognized_s"])
            if span["open_ended"]:
                entry["open_ended_dwells"] += 1
            if span["artwork_id"] in seen:
                entry["revisit_dwells"] += 1
            seen.add(span["artwork_id"])
            if index:
                before = spans[index - 1]["artwork_id"]
                transitions[(before, span["artwork_id"])] = \
                    transitions.get((before, span["artwork_id"]), 0) + 1
        for artwork_id in seen:
            slot(artwork_id)["visits_with_dwell"] += 1
        if spans:
            sequences.append({"visit": visit_id[:8], "path": [s["artwork_id"] for s in spans]})

        for row in rows:
            event = row.get("event")
            if event == "artwork_identified":
                slot(row.get("artwork_id") or "")["identifies"] += 1
            elif event == "artwork_unknown":
                totals["artwork_unknown"] += 1
            elif event == "question":
                # 말이 있었던 모든 턴은 speech_turns, 사실을 조회한 턴만 questions다(grounded).
                # grounded 칸이 없는 옛 기록은 질문으로 세지 않는다. 판별할 수 없기 때문이다.
                artwork_id = row.get("artwork_id") or ""
                entry = slot(artwork_id)
                totals["speech_turns"] += 1
                entry["speech_turns"] += 1
                if row.get("grounded") is not True:
                    continue
                label = row.get("label") if row.get("label") in LABELS else "unknown"
                outcome = row.get("outcome") if row.get("outcome") in OUTCOMES else "unknown"
                totals["questions"] += 1
                totals["labels"][label] += 1
                totals["groups"][group_of(label)] += 1
                totals["outcomes"][outcome] += 1
                if not artwork_id:
                    totals["questions_unassigned"] += 1
                entry["questions"] += 1
                entry["labels"][label] += 1
                entry["groups"][group_of(label)] += 1
                entry["outcomes"][outcome] += 1
                measured = row.get("first_audio_ms")
                if isinstance(measured, int) and measured >= 0:
                    first_audio.append(measured)
                else:
                    unmeasured += 1
            elif event == "comparison":
                slot(row.get("artwork_id") or "")["comparisons"] += 1
            elif event == "usage":
                tokens = slot(row.get("artwork_id") or "")["tokens"]
                for name in tokens:
                    value = row.get(name)
                    if isinstance(value, int):
                        tokens[name] += value
            elif event == "quality":
                issue = str(row.get("issue") or "")
                quality[issue] = quality.get(issue, 0) + 1
            elif event == "visit_end":
                ended += 1
                reason = str(row.get("reason") or "")
                end_reasons[reason] = end_reasons.get(reason, 0) + 1
                if isinstance(row.get("duration_s"), (int, float)):
                    durations.append(row["duration_s"])

    artworks = []
    for entry in sorted(per.values(), key=lambda e: (-e["questions"], -e["dwells"], e["artwork_id"])):
        spans = entry.pop("recognized_s")
        entry["recognized_s"] = _numbers(spans)
        entry["recognized_s"]["open_ended"] = entry.pop("open_ended_dwells")
        artworks.append(entry)

    return {
        "visits": {"total": len(visits), "ended": ended, "no_visit_end": len(visits) - ended,
                   "duration_s": _numbers(durations)},
        "artworks": artworks,
        "totals": totals,
        "transitions": [{"from": a, "to": b, "count": n}
                        for (a, b), n in sorted(transitions.items(), key=lambda kv: -kv[1])],
        "sequences": sequences,
        "first_audio_ms": {"n": len(first_audio), "median": _numbers(first_audio)["median"],
                           "p90": _p90(first_audio), "unmeasured": unmeasured,
                           "note": "관람객이 기다린 시간보다 약 1초 작다(docs/FE1/관람기록_설계.md)"},
        "quality": quality,
        "end_reasons": end_reasons,
    }


def collect(from_day: str, to_day: str, source_kind: str, folder: Path | None = None) -> dict:
    """기간과 자료 종류를 받아 집계 결과를 돌려준다. 여러 종류를 합산하지 않는다."""
    first, last = _parse_day(from_day), _parse_day(to_day)
    if first > last:
        raise ValueError("from is after to")
    if source_kind not in visit_log.SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {visit_log.SOURCE_KINDS}")
    base = folder or visit_log.log_dir()
    rows, files = read_lines(base, _file_days(first - timedelta(days=EDGE_DAYS),
                                              last + timedelta(days=EDGE_DAYS)), source_kind)
    visits, warnings = group_visits(rows, first, last)
    out = summarize(visits)
    out["range"] = {"from": from_day, "to": to_day, "files": files, "attribution": ATTRIBUTION}
    out["source_kind"] = source_kind
    out["warnings"] = warnings
    out["note"] = "visit은 사람이 아니라 폰 연결 1회다. 재연결하면 관람이 둘로 세어진다"
    return out


if __name__ == "__main__":
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    kind = sys.argv[2] if len(sys.argv) > 2 else "team_rehearsal"
    print(json.dumps(collect(day, day, kind), ensure_ascii=False, indent=2))
