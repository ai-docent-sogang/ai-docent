"""합성 체류·질문 입력에서 모의 보고서만 생성한다. 인식 판정기나 실측 수집기가 아니다."""

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "docs/examples/visit_analytics_mock.json"
OUTPUT = ROOT / "docs/FE1_관람분석_모의보고서.md"


def render(data):
    assert data["source_kind"] == "mock", "실측을 모의 보고서에 섞지 않는다"
    visits, dwells, questions = (data[k] for k in ("visits", "dwells", "questions"))
    for rows in (visits, dwells, questions):
        assert len({r["id"] for r in rows}) == len(rows), "중복 ID"
    visit_map = {v["id"]: v for v in visits}
    dwell_map = {d["id"]: d for d in dwells}
    sequences, revisits, transitions = {}, set(), Counter()
    for visit in visits:
        seq = sorted((d for d in dwells if d["visit"] == visit["id"]), key=lambda d: d["start_s"])
        seen = set()
        for d in seq:
            assert 0 <= d["start_s"] < d["end_s"] <= visit["observed_s"]
            assert 0 < d["recognized_s"] <= d["end_s"] - d["start_s"]
            if d["artwork"] in seen:
                revisits.add(d["id"])
            seen.add(d["artwork"])
        for a, b in zip(seq, seq[1:]):
            assert a["end_s"] <= b["start_s"], "체류 구간 겹침"
            if a["artwork"] != b["artwork"]:
                transitions[(a["artwork"], b["artwork"])] += 1
        sequences[visit["id"]] = seq
    assert all(d["visit"] in visit_map for d in dwells)
    for q in questions:
        assert q["visit"] in visit_map
        assert 0 <= q["at_s"] <= visit_map[q["visit"]]["observed_s"]
        assert q["outcome"] in {"answered", "no_source", "error", "unknown"}
        if q["dwell"] is not None:
            d = dwell_map[q["dwell"]]
            assert d["visit"] == q["visit"] and d["start_s"] <= q["at_s"] < d["end_s"]
        if q.get("comparison_artwork"):
            assert any(d["artwork"] == q["comparison_artwork"] and d["end_s"] <= q["at_s"]
                       for d in sequences[q["visit"]]), "비교 대상의 앞선 관람 이력 없음"
        if q.get("failed_text"):
            assert q["outcome"] in {"no_source", "error"}

    recognized = sum(d["recognized_s"] for d in dwells)
    span = sum(d["end_s"] - d["start_s"] for d in dwells)
    linked = [q for q in questions if q["dwell"] is not None]
    unassigned = len(questions) - len(linked)
    outcomes = Counter(q["outcome"] for q in questions)
    questioned = len({q["dwell"] for q in linked})
    comparison_count = sum(bool(q.get("comparison_artwork")) and q["dwell"] in revisits for q in linked)
    ratio = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "N/A"
    lines = [
        "# 관람 분석 모의 보고서", "",
        "**모든 숫자는 합성 데이터다. 실제 관람객·작품·인식 성능에 관한 측정 결과가 아니다.**", "",
        f"자료: `{INPUT.relative_to(ROOT)}`. 가상 작품 A·B·C, 관측 세션 {len(visits)}건. 실제 기간 없음.",
        f"전시 버전: `{data['exhibition_version']}`. 예시 판정: `{data['parameter_version']}`.",
        "체류 판정 뒤의 구간을 직접 구성했다. 아래 집계의 재현성을 보여주며 연속 인식 판정기는 검증하지 않았다.", "",
        f"관측 세션 **{len(visits)}건**, 확정 체류 **{len(dwells)}건**, 재방문 **{len(revisits)}건**, 작품 간 전환 **{sum(transitions.values())}건**.",
        f"인식 기반 체류 합계 **{recognized}초**, 연결 구간 {span}초 중 공백 {span - recognized}초는 주 체류 시간에서 제외.", "",
        "## 작품별 체류와 질문", "",
        "| 가상 작품 | 지속 인식 세션 비율 | 체류 수 | 재방문 수 | 인식 시간 합계 | 중앙값 / 평균 (초) | 공백 (초) | 질문 / 자료 부족 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for art in sorted({d["artwork"] for d in dwells}):
        ds = [d for d in dwells if d["artwork"] == art]
        ids = {d["id"] for d in ds}
        qs = [q for q in linked if q["dwell"] in ids]
        times = [d["recognized_s"] for d in ds]
        gap = sum(d["end_s"] - d["start_s"] - d["recognized_s"] for d in ds)
        lines.append(f"| {art} | {ratio(len({d['visit'] for d in ds}), len(visits))} | {len(ds)} | {len(ids & revisits)} | {sum(times)}초 | {median(times):.1f} / {mean(times):.1f} | {gap} | {len(qs)} / {sum(q['outcome'] == 'no_source' for q in qs)} |")
    lines += ["", "비율의 분모는 관측 세션 전체다. 체류 0건인 M04도 포함한다. 시간 통계의 n은 체류 수이며 사람 수가 아니다.",
              "", "## 관람 순서와 재방문 비교", ""]
    for visit, seq in sequences.items():
        description = " → ".join(d["artwork"] + ("(재방문)" if d["id"] in revisits else "") for d in seq) or "확정 체류 없음"
        lines.append(f"- {visit}: {description}")
    lines += ["", "전환 쌍: " + ", ".join(f"{a}→{b} {n}건" for (a, b), n in sorted(transitions.items())) + ".",
              f"재방문 구간에서 이전 작품을 명시한 비교 질문은 {comparison_count}건이다. 질문의 명시적 비교 대상과 앞선 관람 이력을 함께 확인했다. 재방문 자체를 비교 의도로 해석하지 않는다.",
              "", "## 체류 중 질문과 점검 후보", "",
              f"전체 질문 {len(questions)}건 중 체류 연결 {len(linked)}건, 미연결 {unassigned}건. 질문 있는 체류는 {ratio(questioned, len(dwells))}다.",
              "응답 결과: " + ", ".join(f"{k} {outcomes[k]}건" for k in ("answered", "no_source", "error", "unknown")) + ".",
              "", "| 가상 질문 | 체류 / 유형 | 모의 실패 질문 텍스트 | 점검할 자료 |", "| --- | --- | --- | --- |"]
    for q in questions:
        if q.get("failed_text"):
            art = dwell_map[q["dwell"]]["artwork"]
            check = "제작 목적의 근거·검색 경로" if q["label"] == "context" else "도상 의미의 근거·검색 경로"
            lines.append(f"| {q['id']} | {art} / {q['label']} | {q['failed_text']} | {check} |")
    lines += ["", "이 예시는 A의 재방문과 B의 자료 부족 질문을 다음 점검 대상으로 보여준다. 실제 인기·이해도·해설 부족의 증거는 아니다. no_source는 DB와 검색·지시문을 확인할 후보이며 answered도 정답 보장이 아니다.",
              "", "## 실측 추가 영역과 한계", "",
              "팀원 촬영·리허설 실측: **미수집**. 확보하면 출처·관측 주기·판정 버전·n을 별도 표로 추가하고 모의 값과 합산하지 않는다.",
              "해설 시작·종료: **미수집**. 라벨 읽기·시선·실제 이동 경로·혼잡도는 이 보고서로 측정하지 않는다.",
              "카메라 인식 기반 대리 지표다. T=5초·G=4초·H=1초는 예시값이며 현장 보정이 필요하다.",
              "", "[측정 계획](FE1_관람분석_측정계획.md) · 재생성: `python3 tools/make_visit_analytics_mock_report.py`", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    OUTPUT.write_text(render(data), encoding="utf-8")
    print(f"Generated {OUTPUT.relative_to(ROOT)} (mock only)")
