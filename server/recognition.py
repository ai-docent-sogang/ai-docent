"""카메라 사진과 참조 이미지의 코사인 유사도로 작품 후보를 찾는다 (담당 BE2).

검색에는 `tools/build_index.py`가 생성한 참조 이미지 인덱스를 사용한다.
설치는 `uv sync --extra recognition`, 실행은 `uv run python -m server.recognition 사진.jpg`.
"""

import argparse
import io
import json
from pathlib import Path

DOCENT_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = DOCENT_DIR / "data" / "reference" / "index.npz"
DEFAULT_MODEL = "facebook/dinov2-base"


class Embedder:
    """선택 설치한 이미지 모델로 임베딩을 생성한다."""

    def __init__(self, model_id=DEFAULT_MODEL, revision=None):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.torch = torch
        self.model_id = model_id
        self.processor = AutoImageProcessor.from_pretrained(model_id, revision=revision)
        self.device = pick_device(torch)
        self.model = AutoModel.from_pretrained(model_id, revision=revision).eval().to(self.device)
        # 인덱스 검색에 같은 모델 리비전을 사용하도록 커밋을 기록한다.
        self.revision = revision or getattr(self.model.config, "_commit_hash", None) or ""

    def embed(self, image):
        return self.embed_batch([image])[0]

    def embed_batch(self, images):
        """이미지별 단위 벡터를 반환한다. 정규화한 벡터의 내적은 코사인 유사도다."""
        import numpy as np

        inputs = self.processor(images=[image.convert("RGB") for image in images], return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            if hasattr(self.model, "get_image_features"):
                output = self.model.get_image_features(**inputs)
            else:
                output = self.model(**inputs)
        if isinstance(output, self.torch.Tensor):
            vectors = output
        elif getattr(output, "pooler_output", None) is not None:
            vectors = output.pooler_output
        else:
            vectors = output.last_hidden_state[:, 0]
        vectors = vectors.float().cpu().numpy()
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(vectors).all() or (norms == 0).any():
            raise ValueError("the model returned an invalid vector")
        return vectors / norms


def pick_device(torch):
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def open_for_model(path, size=512):
    """큰 JPEG를 모델 입력에 가까운 크기로 디코딩한다."""
    from PIL import Image

    image = Image.open(path)
    image.draft("RGB", (size, size))
    return image.convert("RGB")


class ReferenceIndex:
    """참조 이미지 인덱스를 읽고 작품 후보를 검색한다."""

    def __init__(self, path=INDEX_PATH, embedder=None):
        import numpy as np

        if not Path(path).exists():
            raise FileNotFoundError(f"{path} not found. Build it first: uv run python -m tools.build_index")
        with np.load(path, allow_pickle=False) as saved:
            self.vectors = saved["vectors"]  # (이미지 수, 벡터 길이)
            self.artwork_ids = saved["artwork_ids"].tolist()
            self.image_files = saved["image_files"].tolist()
            self.info = json.loads(str(saved["info"]))
        self.embedder = embedder or Embedder(self.info["model_id"], self.info.get("model_revision") or None)
        if self.embedder.model_id != self.info["model_id"]:
            raise ValueError("the query model differs from the model that built the index")

    def search(self, image, k=3):
        """작품별 최고 점수로 중복을 제거하고 유사도가 높은 후보를 최대 k개 반환한다."""
        scores = self.vectors @ self.embedder.embed(image)
        best = {}
        for row in scores.argsort()[::-1]:
            artwork_id = self.artwork_ids[row]
            if artwork_id not in best:
                best[artwork_id] = {"artwork_id": artwork_id, "score": round(float(scores[row]), 4),
                                    "image_file": self.image_files[row]}
                if len(best) == k:
                    break
        return list(best.values())

    def search_jpeg(self, jpeg_bytes, k=3):
        from PIL import Image

        with Image.open(io.BytesIO(jpeg_bytes)) as image:
            return self.search(image, k)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find the reference artworks most similar to a photo")
    parser.add_argument("photos", nargs="+")
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    index = ReferenceIndex()
    titles = {}
    manifest = DOCENT_DIR / "data" / "reference" / "manifest.csv"
    if manifest.exists():
        import csv
        with open(manifest, encoding="utf-8-sig") as f:
            titles = {row["artwork_id"]: row["title"] for row in csv.DictReader(f)}
    for photo in args.photos:
        print(photo)
        for rank, hit in enumerate(index.search(open_for_model(photo), args.k), 1):
            print(f"  {rank}. {hit['score']:.3f}  {hit['artwork_id']}  {titles.get(hit['artwork_id'], '')}")
