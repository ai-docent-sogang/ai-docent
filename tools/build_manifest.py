"""Drive로 받은 이미지·해설 데이터를 정리해 이미지 목록표(manifest.csv)와 해설 DB(emuseum_kb.jsonl)를 만든다.

담당: BE2
같이 보는 파일: tools/emuseum_page.py (이용 조건 확인), tools/build_index.py (다음 단계), data/reference/README.md

입력 (git에 올리지 않는 원본):
    data/incoming/docent_kb.jsonl     작품별 이름·작가·e뮤지엄 해설
    data/incoming/images_clean/*.jpg  파일 이름이 e뮤지엄 작품 ID (예: PS0100100100100650400022.jpg)
출력 (git에 올림):
    data/reference/manifest.csv       이미지 1장당 1행. 작품 ID, 파일, 해시, 이용 조건, 출처
    data/kb/emuseum_kb.jsonl          해설 원본에 출처 주소와 확인일을 붙인 것

이용 조건은 작품마다 e뮤지엄 페이지에서 읽는다. 4개씩 동시에 읽어 1,000점에 몇 분 걸린다.
확인 결과는 data/incoming/page_checks.jsonl에 바로바로 저장되므로, 중간에 멈춰도 다시 실행하면 이어서 한다.

실행 (docent/ 폴더에서):
    uv run python -m tools.build_manifest
"""

import argparse
import csv
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from tools.emuseum_page import PAGE_URL, fetch_object_page

DOCENT_DIR = Path(__file__).resolve().parent.parent
INCOMING = DOCENT_DIR / "data" / "incoming"
MANIFEST = DOCENT_DIR / "data" / "reference" / "manifest.csv"
KB_OUT = DOCENT_DIR / "data" / "kb" / "emuseum_kb.jsonl"
PAGE_CACHE = INCOMING / "page_checks.jsonl"  # 작품 페이지 확인 결과(재실행 때 재사용). incoming/이라 git 제외
USER_AGENT = "ai-docent/0.1 (team research prototype)"
load_dotenv(DOCENT_DIR / ".env")  # DOCENT_IMAGES_DIR를 .env에 적어 두면 그 경로를 쓴다
RELIC_ID = re.compile(r"^(PS\d{22})")  # 파일 이름 맨 앞의 e뮤지엄 작품 ID

# 이용 조건별 사용 여부. 사용자 결정 기록:
#   제1유형 - 2026-10-31 공개 라이선스 일괄 승인
#   제4유형 - 2026-11-03 비상업 내부 연구용으로 사용 승인. 변경금지 조건이 있어 이미지를 고쳐 보여 주지 않는다.
RIGHTS_USE = {
    "1": "approved: KOGL type 1 (user bulk rule 2026-10-31)",
    "4": "approved: KOGL type 4, non-commercial internal research only, no altered display (user 2026-11-03)",
}

COLUMNS = ["artwork_id", "image_file", "sha256", "bytes", "title", "author", "has_kb_desc",
           "nationality_period", "classification", "kogl_type", "rights_use", "rights_statement",
           "object_page_url", "checked_at", "note"]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_kb(path):
    """해설 JSONL을 {작품 ID: 기록}으로 읽는다. 같은 ID가 여러 번 나오면 처음 것만 쓴다."""
    kb = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                kb.setdefault(record["id"], record)
    return kb


def check_pages(relic_ids, cache_path, workers=4):
    """작품 페이지를 여러 개 동시에 읽어 이용 조건을 확인한다. 결과는 확인할 때마다 cache_path에 한 줄씩 저장해,
    중간에 멈춰도 다시 실행하면 확인한 작품은 건너뛴다. 돌려주는 값: {작품 ID: 페이지 정보}

    workers: 동시에 여는 페이지 수. 박물관 서버에 부담을 주지 않도록 4 정도로 둔다.
    """
    cache = {}
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    cache[record["artwork_id"]] = record
    todo = [relic_id for relic_id in relic_ids if relic_id not in cache]
    if not todo:
        return cache
    print(f"checking {len(todo)} eMuseum pages ({len(cache)} already checked), {workers} at a time", flush=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    today = date.today().isoformat()

    def check(relic_id):
        try:
            return {"artwork_id": relic_id, **fetch_object_page(relic_id, session), "checked_at": today, "error": ""}
        except requests.RequestException as error:
            return {"artwork_id": relic_id, "checked_at": "", "error": type(error).__name__}

    started = time.time()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool, open(cache_path, "a", encoding="utf-8") as out:
        for number, record in enumerate(pool.map(check, todo), 1):
            if not record["error"]:  # 실패한 작품은 저장하지 않아 다음 실행 때 다시 확인한다
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
            cache[record["artwork_id"]] = record
            if number % 50 == 0 or number == len(todo):
                left = (time.time() - started) / number * (len(todo) - number)
                print(f"  {number}/{len(todo)} pages, about {left / 60:.1f} min left", flush=True)
    return cache


def build_rows(images_dir, kb, cache_path, workers=4):
    """이미지마다 목록표 한 행을 만든다. 같은 작품의 같은 이미지가 두 번 있으면 뒤의 것을 중복으로 표시한다."""
    rows, first_hash = [], {}
    # "이름(1).jpg" 같은 복사본은 원본 뒤에 오도록 정렬해, 중복일 때 원본 이름을 남긴다.
    files = sorted((p for p in images_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")),
                   key=lambda p: (re.search(r"\(\d+\)", p.name) is not None, p.name))
    for path in files:
        match = RELIC_ID.match(path.name)
        digest = sha256(path)
        row = {"image_file": path.name, "sha256": digest, "bytes": path.stat().st_size, "note": ""}
        if not match:
            rows.append({**row, "artwork_id": "", "rights_use": "excluded: file name has no eMuseum ID",
                         "note": "file name has no eMuseum ID"})
            continue
        relic_id = match.group(1)
        record = kb.get(relic_id, {})
        row.update(artwork_id=relic_id, title=record.get("name") or "", author=record.get("author") or "",
                   has_kb_desc="yes" if record.get("desc") else "no", object_page_url=PAGE_URL.format(relic_id))
        if digest in first_hash:
            row["note"] = f"duplicate of {first_hash[digest]}"
        first_hash.setdefault(digest, path.name)
        rows.append(row)

    # 페이지 확인은 이미지가 아니라 작품 단위로 한 번씩만 한다.
    pages = check_pages(sorted({row["artwork_id"] for row in rows if row["artwork_id"]}), cache_path, workers)
    for row in rows:
        if not row["artwork_id"]:
            continue
        page = pages.get(row["artwork_id"], {})
        if page.get("error"):
            row["note"] = (row["note"] + "; " if row["note"] else "") + f"page check failed: {page['error']}"
        row.update(title=page.get("page_title") or row["title"], nationality_period=page.get("page_nationality_period", ""),
                   classification=page.get("page_classification", ""), kogl_type=page.get("page_kogl_type", ""),
                   rights_statement=page.get("page_rights_statement", ""), checked_at=page.get("checked_at", ""))
        if row["note"].startswith("duplicate"):
            row["rights_use"] = "excluded: duplicate image"
        else:
            row["rights_use"] = RIGHTS_USE.get(row["kogl_type"], f"excluded: KOGL type '{row['kogl_type'] or 'none'}' not approved")
    return rows


def write_kb(kb, path, today):
    """해설 원본에 출처와 확인일을 붙여 저장한다. 해설은 박물관 원문(한국어)이며 팀 검수 전이다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for relic_id, record in kb.items():
            out = {**record, "source": "e뮤지엄 해설 (원문, 팀 검수 전)", "object_page_url": PAGE_URL.format(relic_id),
                   "copied_at": today}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Build data/reference/manifest.csv and data/kb/emuseum_kb.jsonl")
    parser.add_argument("--images", default=os.getenv("DOCENT_IMAGES_DIR", str(INCOMING / "images_clean")))
    parser.add_argument("--kb", default=str(INCOMING / "docent_kb.jsonl"))
    parser.add_argument("--workers", type=int, default=4, help="eMuseum pages checked at the same time")
    args = parser.parse_args()
    images_dir, kb_path = Path(args.images), Path(args.kb)
    for required in (images_dir, kb_path):
        if not required.exists():
            raise SystemExit(f"{required} not found. Download the Drive folder into data/incoming/ (or set DOCENT_IMAGES_DIR in .env)")

    kb = load_kb(kb_path)
    rows = build_rows(images_dir, kb, PAGE_CACHE, args.workers)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in COLUMNS} for row in rows)
    write_kb(kb, KB_OUT, date.today().isoformat())

    image_ids = {row["artwork_id"] for row in rows if row["artwork_id"]}
    usable = [row for row in rows if row["rights_use"].startswith("approved")]
    print(f"\nimages {len(rows)} (artworks {len(image_ids)}), usable {len(usable)} -> {MANIFEST.relative_to(DOCENT_DIR)}")
    for reason in sorted({row["rights_use"] for row in rows if not row["rights_use"].startswith("approved")}):
        print(f"  {reason}: {sum(row['rights_use'] == reason for row in rows)}")
    print(f"kb records {len(kb)} -> {KB_OUT.relative_to(DOCENT_DIR)}")
    print(f"  artworks with an image but no kb record: {len(image_ids - kb.keys())}")
    print(f"  kb records with no image: {len(kb.keys() - image_ids)}")


if __name__ == "__main__":
    main()
