"""시험 사진 파일 이름에서 정답표(data/eval/recognition_answers.csv)의 나머지 칸을 채운다.

담당: BE2
같이 보는 파일: data/eval/README.md (파일 이름 규칙), data/reference/manifest.csv (작품 ID·제목)

정답은 사람이 아는 정보(어떤 그림을 받았는지)에서 와야 한다. 인식 모델 결과로 정답을 채우면 시험이 되지 않는다.
그래서 사진을 저장할 때 파일 이름에 작품을 적어 두면, 이 도구가 그 이름으로 작품 ID를 찾아 표를 채운다.

파일 이름 규칙:  작품__조건__번호.jpg   (밑줄 두 개로 구분)
    작품: e뮤지엄 ID(PS...), 또는 제목 일부(예: 씨름), 기준 DB에 없는 그림이면 none
    조건: 촬영 조건(예: web-gallery, web-angle, web-glare). 생략 가능
    예) 씨름__web-gallery__01.jpg, PS0100100100100650400022__web-angle__02.jpg, none__poster__01.jpg

실행 (docent/ 폴더에서):
    uv run python -m tools.make_answer_sheet
이미 표에 있는 사진은 건드리지 않고 새 사진만 추가한다. 작품을 하나로 정하지 못하면 artwork_id를 CHECK로 두고
후보를 note에 적으므로, 그 줄만 직접 고치면 된다.
"""

import csv
import hashlib
import re
import unicodedata
from datetime import date
from pathlib import Path

DOCENT_DIR = Path(__file__).resolve().parent.parent
PHOTOS = DOCENT_DIR / "data" / "test_photos"
ANSWERS = DOCENT_DIR / "data" / "eval" / "recognition_answers.csv"
MANIFEST = DOCENT_DIR / "data" / "reference" / "manifest.csv"
COLUMNS = ["photo_file", "artwork_id", "condition", "source_url", "collected_by", "collected_at", "note"]
RELIC_ID = re.compile(r"PS\d{22}")


def load_manifest():
    """작품 ID → 제목, 그리고 기준 이미지 해시 목록(같은 파일을 시험 사진으로 쓰는지 확인용)."""
    titles, hashes = {}, {}
    with open(MANIFEST, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["artwork_id"]:
                titles.setdefault(row["artwork_id"], row["title"])
                hashes[row["sha256"]] = row["artwork_id"]
    return titles, hashes


def resolve(key, titles):
    """파일 이름의 작품 부분을 작품 ID로 바꾼다. 돌려주는 값: (artwork_id, note)"""
    if key.lower() == "none":
        return "none", ""
    match = RELIC_ID.search(key)
    if match:
        found = match.group(0)
        return (found, "") if found in titles else ("CHECK", f"{found} is not in manifest.csv")
    # 맥은 한글 파일 이름을 자모가 분리된 형태(NFD)로 저장해, 같은 글자여도 그대로 비교하면 다르게 나온다.
    def plain(text):
        return unicodedata.normalize("NFC", text).replace(" ", "").replace("_", "")

    wanted = plain(key)
    hits = [artwork_id for artwork_id, title in titles.items() if wanted and wanted in plain(title)]
    if len(hits) == 1:
        return hits[0], f"matched title: {titles[hits[0]]}"
    if not hits:
        return "CHECK", f"no title contains '{key}'"
    shown = "; ".join(f"{artwork_id} {titles[artwork_id]}" for artwork_id in hits[:5])
    return "CHECK", f"{len(hits)} titles contain '{key}': {shown}" + (" ..." if len(hits) > 5 else "")


def main():
    if not MANIFEST.exists():
        raise SystemExit(f"{MANIFEST} not found. Run first: uv run python -m tools.build_manifest")
    if not PHOTOS.exists():
        raise SystemExit(f"{PHOTOS} not found. Put the test photos there first.")
    titles, reference_hashes = load_manifest()
    existing = []
    if ANSWERS.exists():
        with open(ANSWERS, encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    known = {row["photo_file"] for row in existing}

    new_rows = []
    for path in sorted(p for p in PHOTOS.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")):
        if path.name in known:
            continue
        parts = path.stem.split("__")
        artwork_id, note = resolve(parts[0], titles)
        if hashlib.sha256(path.read_bytes()).hexdigest() in reference_hashes:
            # 기준 이미지와 똑같은 파일이면 정답률이 부풀려진다. 실제 촬영과 비슷한 사진으로 바꾸는 게 좋다.
            note = (note + "; " if note else "") + "same file as a reference image (not a fair test)"
        new_rows.append({"photo_file": path.name, "artwork_id": artwork_id,
                         "condition": parts[1] if len(parts) > 1 else "", "source_url": "",
                         "collected_by": "", "collected_at": date.today().isoformat(), "note": note})

    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    with open(ANSWERS, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in COLUMNS} for row in existing + new_rows)
    check = [row for row in new_rows if row["artwork_id"] == "CHECK"]
    print(f"added {len(new_rows)} photos ({len(existing)} already listed) -> {ANSWERS.relative_to(DOCENT_DIR)}")
    print(f"  need a manual fix (artwork_id = CHECK): {len(check)}")
    for row in check:
        print(f"    {row['photo_file']}: {row['note']}")


if __name__ == "__main__":
    main()
