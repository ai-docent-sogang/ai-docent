"""Live가 unknown이라고 한 작품을 기준 이미지 검색으로 한 번 더 판단한다 (담당 FE1·BE2).

LIVE_RECOGNIZER_FALLBACK=on일 때만 쓴다. torch를 이때 처음 불러오므로 off면 설치하지 않아도 된다.
사진은 메모리에서만 쓰고 저장하지 않는다.
"""
import asyncio
import os

_recognizer = None


def _get_recognizer(artworks):
    global _recognizer
    if _recognizer is None:
        from ..artwork_recognizer import ArtworkRecognizer   # recognition extra가 필요한 import
        _recognizer = ArtworkRecognizer(artworks)
    return _recognizer


async def recognize_unknown(jpeg, artworks, client):
    """작품 ID를 돌려준다. 못 찾거나 실패하면 빈 문자열. Live 대화를 깨뜨리지 않는다."""
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not jpeg or not model:
        return ""
    try:
        recognizer = _get_recognizer(artworks)
        found = await asyncio.to_thread(recognizer.recognize, jpeg, client, model)
    except Exception as e:   # 설치 누락, 색인 불일치, 네트워크 오류 모두 unknown으로 둔다
        print(f"[live] 인식 보조 실패(unknown 유지): {e!r}"[:200])
        return ""
    return found if found in artworks else ""
