"""카메라 사진과 가장 비슷한 기준 이미지를 찾아 작품 후보를 고르는 파일 (개발계획서 5장 2안).

담당: BE2
같이 보는 파일: tools/build_index.py (기준 이미지 벡터를 미리 만듦), data/reference/manifest.csv, data/reference/README.md

원리: 이미지 모델(DINOv2 등)이 사진 한 장을 숫자 묶음(벡터, 임베딩)으로 바꾼다. 같은 그림을 찍은 사진은
벡터의 방향이 비슷해서, 두 벡터 사이 각도의 코사인(코사인 유사도, 1에 가까울수록 비슷)이 크게 나온다.
카메라 사진의 벡터를 기준 이미지 1,000여 장의 벡터와 모두 비교해 점수가 높은 순으로 후보를 돌려준다.

지금 단계: 후보 찾기만 한다. 서버(/api/turn)에는 아직 연결하지 않았다.
"이 점수 이상이면 확정"하는 기준은 회화실 시험 사진으로 정답률을 잰 뒤 정한다(역할 가이드 4장).

필요한 설치: uv sync --extra recognition (torch, transformers 등. 처음 한 번 수백 MB를 내려받음)
사진 한 장으로 시험해 보기 (docent/ 폴더에서):
    uv run python -m server.recognition 찍은사진.jpg
"""

import argparse
import io
import json
from pathlib import Path

DOCENT_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = DOCENT_DIR / "data" / "reference" / "index.npz"
DEFAULT_MODEL = "facebook/dinov2-base"


class Embedder:
    """사진을 벡터로 바꾸는 모델. 무거운 라이브러리는 실제로 쓸 때 불러온다(인식을 안 쓰는 팀원은 설치 불필요)."""

    def __init__(self, model_id=DEFAULT_MODEL, revision=None):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.torch = torch
        self.model_id = model_id
        self.processor = AutoImageProcessor.from_pretrained(model_id, revision=revision)
        self.model = AutoModel.from_pretrained(model_id, revision=revision).eval()
        # 같은 모델이라도 버전이 다르면 벡터가 달라진다. 기준 벡터를 만든 버전을 기록해 두고 검색 때 맞춘다.
        self.revision = revision or getattr(self.model.config, "_commit_hash", None) or ""

    def embed(self, image):
        """PIL 이미지 한 장 → 길이 1로 맞춘(정규화한) 벡터. 길이를 1로 맞추면 내적이 곧 코사인 유사도가 된다."""
        import numpy as np

        inputs = self.processor(images=image.convert("RGB"), return_tensors="pt")
        with self.torch.inference_mode():
            if hasattr(self.model, "get_image_features"):
                # CLIP처럼 글과 그림을 함께 다루는 모델은 그림 쪽 벡터만 따로 꺼낸다.
                output = self.model.get_image_features(**inputs)
            else:
                output = self.model(**inputs)
        if isinstance(output, self.torch.Tensor):
            vector = output
        elif getattr(output, "pooler_output", None) is not None:
            # DINOv2의 pooler_output은 맨 앞 [CLS] 토큰(그림 전체를 요약한 값)을 정규화한 것이다.
            vector = output.pooler_output
        else:
            vector = output.last_hidden_state[:, 0]
        vector = vector[0].float().cpu().numpy()
        norm = np.linalg.norm(vector)
        if not np.isfinite(vector).all() or norm == 0:
            raise ValueError("the model returned an invalid vector")
        return vector / norm


class ReferenceIndex:
    """tools/build_index.py가 만든 index.npz를 읽어 후보를 찾는다."""

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
        """사진과 가장 비슷한 작품 k개를 [{"artwork_id", "score", "image_file"}, ...]로 돌려준다.

        한 작품에 기준 이미지가 여러 장이면 그중 가장 높은 점수만 쓴다(같은 작품이 후보를 독차지하지 않게).
        """
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
        """서버가 받은 카메라 사진(JPEG 바이트)으로 검색한다. /api/turn에 연결할 때 쓸 함수."""
        from PIL import Image

        with Image.open(io.BytesIO(jpeg_bytes)) as image:
            return self.search(image, k)


if __name__ == "__main__":
    from PIL import Image

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
        with Image.open(photo) as image:
            print(photo)
            for rank, hit in enumerate(index.search(image, args.k), 1):
                print(f"  {rank}. {hit['score']:.3f}  {hit['artwork_id']}  {titles.get(hit['artwork_id'], '')}")
