"""Recognize an uploaded camera frame against the 11-work demo index."""
import io
from functools import cached_property
from pathlib import Path

from .artwork_crop import crop_artwork, locate_artwork
from .catalog import mapping_rows, read_csv
from .recognition import DOCENT_DIR, ReferenceIndex

DEFAULT_REFERENCE = DOCENT_DIR / "data/incoming/exhibit_11/reference"
KANG_REFERENCE_ID = "PS0100100101601056200000"


class InvalidJpeg(ValueError):
    """The uploaded bytes could not be decoded as a JPEG."""


class ArtworkRecognizer:
    def __init__(self, artworks, reference_dir=DEFAULT_REFERENCE):
        self.artworks = artworks
        self.reference_dir = Path(reference_dir)

    @cached_property
    def candidates(self):
        rows = mapping_rows(self.artworks.values(), read_csv(self.reference_dir / "demo_manifest.csv"))
        mapping = {row["reference_artwork_id"]: row["service_artwork_id"]
                   for row in rows if row["mapping_status"] == "exact_relic_id"}
        index = ReferenceIndex(self.reference_dir / "index_demo.npz")
        if len(mapping) != 11 or not mapping.keys() <= set(index.artwork_ids):
            raise ValueError("The demo index must contain 11 approved works mapped to the service catalog")
        return index, mapping

    def recognize(self, jpeg_bytes, client, model):
        from PIL import Image, ImageOps

        try:
            with Image.open(io.BytesIO(jpeg_bytes), formats=["JPEG"]) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, Image.DecompressionBombError) as exc:
            raise InvalidJpeg from exc
        with image:
            box = locate_artwork(
                client, model, image,
                "the artwork indicated by the visible index fingertip, or the main artwork if no fingertip is visible",
            )
            if box is None:
                return "unknown"
            index, mapping = self.candidates
            with crop_artwork(image, box) as crop:
                hits = index.search(crop, k=1, allowed_ids=mapping)
        if not hits:
            return "unknown"
        hit = hits[0]
        threshold = 0.85 if hit["artwork_id"] == KANG_REFERENCE_ID else 0.60
        return mapping[hit["artwork_id"]] if hit["score"] >= threshold else "unknown"
