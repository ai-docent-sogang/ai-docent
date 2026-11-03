"""manifest.csv에서 사용 승인된 기준 이미지를 모두 벡터로 바꿔 data/reference/index.npz에 저장한다.

담당: BE2
같이 보는 파일: server/recognition.py (벡터 만드는 방법과 검색), tools/build_manifest.py (이전 단계)

- manifest.csv의 rights_use가 "approved"로 시작하는 행만 쓴다(중복·이용 조건 미확인 이미지 제외).
- 파일의 해시가 manifest와 다르면 다른 파일로 보고 건너뛴다(팀원끼리 같은 이미지 세트를 쓰는지 확인).
- index.npz는 git에 올리지 않는다. 같은 manifest와 같은 모델이면 누가 만들어도 같은 결과가 나온다.

실행 (docent/ 폴더에서, 처음에는 모델을 내려받아 몇 분 더 걸림):
    uv sync --extra recognition
    uv run python -m tools.build_index
    uv run python -m tools.build_index --model openai/clip-vit-base-patch32 --output data/reference/index_clip.npz
"""

import argparse
import csv
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from server.recognition import DEFAULT_MODEL, INDEX_PATH, Embedder, open_for_model

DOCENT_DIR = Path(__file__).resolve().parent.parent
MANIFEST = DOCENT_DIR / "data" / "reference" / "manifest.csv"
load_dotenv(DOCENT_DIR / ".env")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    import numpy as np

    parser = argparse.ArgumentParser(description="Embed approved reference images into index.npz")
    parser.add_argument("--images", default=os.getenv("DOCENT_IMAGES_DIR", str(DOCENT_DIR / "data" / "incoming" / "images_clean")))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(INDEX_PATH))
    parser.add_argument("--batch", type=int, default=16, help="images per model call; lower it if memory runs out")
    args = parser.parse_args()
    images_dir = Path(args.images)
    if not MANIFEST.exists():
        raise SystemExit(f"{MANIFEST} not found. Run first: uv run python -m tools.build_manifest")

    with open(MANIFEST, encoding="utf-8-sig") as f:
        rows = [row for row in csv.DictReader(f) if row["rights_use"].startswith("approved")]
    embedder = Embedder(args.model)
    print(f"model {embedder.model_id} on {embedder.device}; {len(rows)} approved images", flush=True)
    vectors, artwork_ids, image_files, skipped = [], [], [], []
    batch_images, batch_rows = [], []
    started = time.time()

    def flush():
        """모아 둔 이미지를 한 번에 벡터로 바꾼다."""
        if batch_images:
            vectors.extend(embedder.embed_batch(batch_images))
            artwork_ids.extend(row["artwork_id"] for row in batch_rows)
            image_files.extend(row["image_file"] for row in batch_rows)
            batch_images.clear()
            batch_rows.clear()

    for number, row in enumerate(rows, 1):
        path = images_dir / row["image_file"]
        if not path.exists():
            skipped.append((row["image_file"], "missing"))
        elif file_sha256(path) != row["sha256"]:
            skipped.append((row["image_file"], "hash differs from manifest"))
        else:
            try:
                batch_images.append(open_for_model(path))
                batch_rows.append(row)
            except OSError as error:
                skipped.append((row["image_file"], str(error)))
        if len(batch_images) >= args.batch:
            flush()
        if number % 100 == 0:
            left = (time.time() - started) / number * (len(rows) - number)
            print(f"{number}/{len(rows)} images, about {left / 60:.1f} min left", flush=True)
    flush()
    if not vectors:
        raise SystemExit(f"No image could be embedded; skipped: {skipped[:5]}")

    info = {"model_id": embedder.model_id, "model_revision": embedder.revision, "dimension": int(vectors[0].shape[0]),
            "manifest_sha256": file_sha256(MANIFEST), "images": len(vectors), "skipped": skipped,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, vectors=np.stack(vectors).astype(np.float32), artwork_ids=np.asarray(artwork_ids),
                        image_files=np.asarray(image_files), info=json.dumps(info, ensure_ascii=False))
    print(f"\n{len(vectors)} images ({len(set(artwork_ids))} artworks) -> {output}; skipped {len(skipped)}")
    for name, reason in skipped[:20]:
        print(f"  skipped {name}: {reason}")


if __name__ == "__main__":
    main()
