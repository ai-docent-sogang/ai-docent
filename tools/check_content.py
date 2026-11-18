"""콘텐츠 CSV 검사 도구

담당: BE2 (docs/역할_가이드.md 4장, 11/5–11/11 "CSV 검사 도구")
사용자: FE3 — CSV를 고칠 때마다 실행해 오류 목록을 본다.
같이 보는 파일: data/artworks.csv, data/comparisons.csv, server/content.py (서버가 CSV를 읽는 방식)

찾아야 할 오류 (가이드 기준):
- 필수 칸이 비어 있음 (artwork_id, title_en, key_facts, official_url, checked_at 등)
- artwork_id·comparison_id 중복
- 구분자 실수: key_facts·similarities·differences는 |, profile_tags는 ;
- comparisons.csv가 artworks.csv에 없는 artwork_id를 가리킴
- verification_status 값이 정해진 값이 아님 (현재 데이터: verified, page_verified, unverified)

실행 형태:
    uv run python -m tools.check_content
"""

"""BE2 콘텐츠 검사: python -m tools.check_content [--foreign-csv 수집파일.csv]."""
import argparse
import csv
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from server.catalog import DATA_DIR, mapping_rows, read_csv


def validate_rows(rows, required, id_field, filename):
    issues, seen = [], set()
    for number, row in enumerate(rows, 2):
        prefix = f"{filename}:{number}"
        for field in required:
            if not row.get(field, "").strip():
                issues.append(("ERROR", f"{prefix}: {field} 필수 값 누락"))
        identifier = row.get(id_field, "").strip()
        if identifier in seen:
            issues.append(("ERROR", f"{prefix}: 중복 {id_field}={identifier}"))
        seen.add(identifier)
        status = row.get("verification_status", "")
        if status not in {"verified", "page_verified", "unverified"}:
            issues.append(("ERROR", f"{prefix}: 잘못된 verification_status={status!r}"))
        elif status == "unverified":
            issues.append(("WARNING", f"{prefix}: 미검수 자료 {identifier}"))
        for field in ("official_url", "foreign_url"):
            if row.get(field):
                url = urlparse(row[field])
                if url.scheme not in {"https", "http"} or not url.hostname:
                    issues.append(("ERROR", f"{prefix}: 잘못된 {field}"))
        if row.get("checked_at"):
            try:
                date.fromisoformat(row["checked_at"])
            except ValueError:
                issues.append(("ERROR", f"{prefix}: checked_at은 YYYY-MM-DD 형식이어야 함"))
        for field in ("key_facts", "similarities", "differences"):
            value = row.get(field, "")
            if value and any(not part.strip() for part in value.split("|")):
                issues.append(("ERROR", f"{prefix}: {field}에 빈 | 조각 존재"))
        tags = row.get("profile_tags", "")
        if tags and ("|" in tags or "," in tags or any(not part.strip() for part in tags.split(";"))):
            issues.append(("ERROR", f"{prefix}: profile_tags 구분자는 ; 사용"))
    return issues


def check(data_dir=DATA_DIR, foreign_csv=None):
    data_dir, issues, tables = Path(data_dir), [], {}
    specs = [("artworks.csv", "artwork_id", {"artwork_id", "title_en", "key_facts", "official_url", "checked_at", "verification_status"}),
             ("comparisons.csv", "comparison_id", {"comparison_id", "artwork_id", "foreign_title", "foreign_url", "similarities", "differences", "checked_at", "verification_status"})]
    for filename, id_field, required in specs:
        path = data_dir / filename
        try:
            rows = read_csv(path)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                headers = csv.DictReader(stream).fieldnames or []
            missing = required - set(headers)
            if missing:
                issues.append(("ERROR", f"{filename}: 필수 열 누락 {sorted(missing)}"))
            if not rows:
                issues.append(("WARNING", f"{filename}: 데이터 행 없음"))
            issues.extend(validate_rows(rows, required, id_field, filename))
            tables[filename] = rows
        except (OSError, ValueError) as exc:
            issues.append(("ERROR", f"{filename}: {exc}"))
            tables[filename] = []
    artworks = tables["artworks.csv"]
    artwork_ids = {r.get("artwork_id") for r in artworks}
    foreign_rows = []
    if foreign_csv:
        try:
            foreign_rows = read_csv(foreign_csv)
            issues.extend(validate_rows(foreign_rows, {"artwork_id", "title", "official_url", "verification_status"},
                                        "artwork_id", str(foreign_csv)))
        except (OSError, ValueError) as exc:
            issues.append(("ERROR", f"foreign CSV: {exc}"))
    foreign_ids = {r.get("artwork_id") for r in foreign_rows}
    for row in tables["comparisons.csv"]:
        if row.get("artwork_id") not in artwork_ids:
            issues.append(("ERROR", f"{row.get('comparison_id')}: 존재하지 않는 국내 작품 ID"))
        if row.get("verification_status") == "page_verified":
            issues.append(("WARNING", f"{row.get('comparison_id')}: 비교쌍은 verified 상태만 답변에 사용됨"))
        if row.get("foreign_artwork_id") and foreign_csv and row["foreign_artwork_id"] not in foreign_ids:
            issues.append(("ERROR", f"{row.get('comparison_id')}: 존재하지 않는 해외 작품 ID"))
    for artwork in artworks:
        if artwork.get("on_view_status") in {None, "", "확인 필요", "unverified"}:
            issues.append(("WARNING", f"{artwork.get('artwork_id')}: 실제 전시 여부 확인 필요"))
    try:
        for row in mapping_rows(artworks, read_csv(data_dir / "reference/manifest.csv")):
            if row["mapping_status"] == "missing_reference":
                issues.append(("WARNING", f"{row['service_artwork_id']}: 동일 relicId 승인 참조 이미지 없음"))
    except (OSError, ValueError, KeyError) as exc:
        issues.append(("ERROR", f"reference mapping: {exc}"))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--foreign-csv", type=Path)
    parser.add_argument("--strict", action="store_true", help="경고도 실패로 처리")
    args = parser.parse_args()
    issues = check(args.data_dir, args.foreign_csv)
    for level, message in issues:
        print(f"{level}: {message}")
    errors = sum(level == "ERROR" for level, _ in issues)
    warnings = sum(level == "WARNING" for level, _ in issues)
    print(f"Result: {errors} errors, {warnings} warnings")
    return int(errors > 0 or (args.strict and warnings > 0))


if __name__ == "__main__":
    raise SystemExit(main())
