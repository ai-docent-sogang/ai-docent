"""BE2: 인식 relicId → 서비스 작품 ID → 출처 있는 콘텐츠 조회. 외부 API 호출 없음.

ContentCatalog.get_context()를 BE1의 요청-응답/Live 도구에서 공통으로 사용할 수 있다.
미검수 e뮤지엄 원문과 해외 수집 자료는 답변 근거에서 제외하고 검수 대기 정보만 돌려준다.
"""
import csv
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .content import DATA_DIR, load_artworks, load_comparisons, rank_comparisons

APPROVED_ARTWORK = {"verified", "page_verified"}
APPROVED_MAPPING = {"exact_relic_id", "verified"}


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"CSV 열 개수가 맞지 않습니다: {path}")
        return rows


def relic_id(url):
    parsed = urlparse(url or "")
    if parsed.hostname not in {"emuseum.go.kr", "www.emuseum.go.kr"}:
        return ""
    return (parse_qs(parsed.query).get("relicId") or [""])[0]


def source_key(url):
    """같은 기관의 같은 작품 URL만 결합. 제목/작가 유사도로 결합하지 않는다."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    return (host, path, parsed.query) if host else None


def unique_rows(rows, key, label):
    result = {}
    for row in rows:
        value = row.get(key, "").strip()
        if not value or value in result:
            raise ValueError(f"{label}: 빈 ID 또는 중복 ID: {value!r}")
        result[value] = row
    return result


def mapping_rows(artworks, manifest):
    """공식 URL의 정확한 relicId로만 연결. 누락 참조도 보고서에 남긴다."""
    references = {}
    for row in manifest:
        references.setdefault(row["artwork_id"], []).append(row)
    result = []
    used = set()
    for artwork in artworks:
        reference_id = relic_id(artwork.get("official_url"))
        if reference_id and reference_id in used:
            raise ValueError(f"같은 relicId가 여러 서비스 작품에 사용됨: {reference_id}")
        if reference_id:
            used.add(reference_id)
        matches = references.get(reference_id, [])
        approved = [r for r in matches if r.get("rights_use", "").startswith("approved")]
        result.append({"reference_artwork_id": reference_id,
            "service_artwork_id": artwork["artwork_id"],
            "mapping_status": "exact_relic_id" if approved else "missing_reference",
            "image_files": "|".join(r["image_file"] for r in approved),
            "official_url": artwork.get("official_url", ""),
            "note": "공식 페이지 relicId 일치; 이미지 내용·현장 전시 여부는 별도 확인" if approved
                    else "동일 relicId의 승인 참조 이미지 없음. 화첩 전체를 낱장으로 추정 연결하지 않음"})
    return result


class ContentCatalog:
    def __init__(self, data_dir=DATA_DIR, foreign_csv=None, mapping_path=None):
        data_dir = Path(data_dir)
        artwork_rows = read_csv(data_dir / "artworks.csv")
        unique_rows(artwork_rows, "artwork_id", "artworks")
        self.artworks = load_artworks(data_dir / "artworks.csv")
        comparisons = read_csv(data_dir / "comparisons.csv")
        unique_rows(comparisons, "comparison_id", "comparisons")
        self.comparisons = load_comparisons(data_dir / "comparisons.csv")
        for row in self.comparisons:
            if row["artwork_id"] not in self.artworks:
                raise ValueError(f"비교쌍의 국내 작품 없음: {row['comparison_id']}")
        manifest = read_csv(data_dir / "reference/manifest.csv")
        approved_references = {r["artwork_id"] for r in manifest if r.get("rights_use", "").startswith("approved")}
        mapping = read_csv(mapping_path) if mapping_path else mapping_rows(artwork_rows, manifest)
        self.mapping = {}
        for row in mapping:
            if row.get("mapping_status") not in APPROVED_MAPPING:
                continue
            reference_id, service_id = row["reference_artwork_id"], row["service_artwork_id"]
            if reference_id not in approved_references or service_id not in self.artworks:
                raise ValueError(f"매핑이 없는 참조/서비스 작품을 가리킴: {reference_id} → {service_id}")
            if reference_id in self.mapping:
                raise ValueError(f"중복 참조 매핑: {reference_id}")
            self.mapping[reference_id] = service_id
        kb_path = data_dir / "kb/emuseum_kb.jsonl"
        self.kb = {}
        if kb_path.exists():
            with kb_path.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if line.strip():
                        item = json.loads(line)
                        if item["id"] in self.kb:
                            raise ValueError(f"중복 해설 ID: {item['id']}")
                        self.kb[item["id"]] = item
        foreign_csv = Path(foreign_csv) if foreign_csv else data_dir / "foreign/foreign_artworks.csv"
        self.foreign = {}
        if foreign_csv.exists():
            rows = read_csv(foreign_csv)
            unique_rows(rows, "artwork_id", "foreign_artworks")
            for row in rows:
                key = source_key(row.get("official_url"))
                if key:
                    if key in self.foreign:
                        raise ValueError(f"중복 해외 작품 출처: {row['official_url']}")
                    self.foreign[key] = row

    def resolve(self, recognition_id):
        """현재 recognizer의 relicId와 수동 선택의 서비스 ID 모두 지원한다."""
        if recognition_id in self.artworks:
            return recognition_id
        return self.mapping.get(recognition_id, "unknown")

    def get_context(self, recognition_id, profile=None, used_ids=()):
        service_id = self.resolve(recognition_id)
        artwork = self.artworks.get(service_id)
        if not artwork:
            return {"artwork_id": "unknown", "reason": "unmapped_reference", "artwork": None,
                    "emuseum_description": None, "comparisons": [], "review_queue": []}
        if artwork.get("verification_status") not in APPROVED_ARTWORK:
            return {"artwork_id": "unknown", "reason": "unverified_artwork", "artwork": None,
                    "emuseum_description": None, "comparisons": [], "review_queue": []}
        queue = []
        result = {"artwork_id": service_id, "reason": "matched", "artwork": {
            key: artwork.get(key) for key in ("artwork_id", "title_ko", "title_en", "artist", "date",
                "medium", "key_facts", "official_url", "checked_at", "verification_status")},
            "emuseum_description": None, "comparisons": [], "review_queue": queue}
        kb = self.kb.get(relic_id(artwork.get("official_url")))
        if kb and kb.get("desc"):
            if (kb.get("verification_status") in APPROVED_ARTWORK and kb.get("object_page_url")
                    and relic_id(kb["object_page_url"]) == kb["id"]):
                result["emuseum_description"] = {"text": kb["desc"], "source_url": kb["object_page_url"]}
            else:
                queue.append({"type": "emuseum_description", "id": kb["id"], "reason": "needs_review"})
        ranked = rank_comparisons(self.comparisons, service_id, profile or {}, set(used_ids))
        for comparison in ranked:
            record = {key: comparison.get(key) for key in ("comparison_id", "foreign_title", "foreign_artist",
                "foreign_date", "foreign_collection", "foreign_url", "angle", "similarities", "differences",
                "source_note", "checked_at", "verification_status")}
            record["foreign_artwork"] = None
            foreign = self.foreign.get(source_key(comparison.get("foreign_url")))
            if foreign:
                if foreign.get("verification_status") == "verified":
                    record["foreign_artwork"] = {key: foreign.get(key) for key in ("artwork_id", "title", "artist",
                        "date_display", "medium", "description", "official_url", "collected_at")}
                else:
                    queue.append({"type": "foreign_artwork", "id": foreign["artwork_id"], "reason": "needs_review"})
            else:
                queue.append({"type": "foreign_artwork", "id": comparison["comparison_id"], "reason": "not_collected"})
            result["comparisons"].append(record)
        return result
