"""Gemini artwork localization shared by evaluation and the turn endpoint."""
import io
import json
from math import ceil, floor

from google.genai import types


def parse_box(text):
    box = json.loads(text)
    if isinstance(box, dict):
        box = box["box_2d"]
    if box is None or box == []:
        return None
    if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
        raise ValueError("Expected four integer box coordinates")
    top, left, bottom, right = box
    if not (0 <= left < right <= 1000 and 0 <= top < bottom <= 1000):
        raise ValueError("Invalid normalized box coordinates")
    return tuple(v / 1000 for v in (left, top, right, bottom))


def locate_artwork(client, model, image, target):
    with io.BytesIO() as encoded:
        image.save(encoded, format="JPEG", quality=90)
        part = types.Part.from_bytes(data=encoded.getvalue(), mime_type="image/jpeg")
    response = client.models.generate_content(
        model=model,
        contents=[
            part,
            f"Locate {target}. Bound the actual artwork, excluding the display and surrounding UI. "
            "Return box_2d as [ymin, xmin, ymax, xmax], integers normalized to 0-1000. "
            "Use an empty box_2d array if the target cannot be located.",
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "properties": {"box_2d": {"type": "array", "items": {"type": "integer"}, "maxItems": 4}},
                "required": ["box_2d"],
            },
        ),
    )
    return parse_box(response.text)


def crop_artwork(image, box):
    left, top, right, bottom = box
    return image.crop((floor(left * image.width), floor(top * image.height),
                       ceil(right * image.width), ceil(bottom * image.height)))
