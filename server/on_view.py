"""전시에서 내려간 작품을 인식 후보에서 빼는 런타임 상태 (담당 FE1).

운영 페이지(`/admin`)가 켜고 끈다. 끈 작품은 Live의 도구 값 목록과 전시작 목록, 함수 결과에서
함께 빠지므로 도슨트가 그 작품을 알아보지 못한다.

**상태를 파일에 남기지 않는다.** "어떤 작품이 전시에 있나"의 단일 출처는
`data/artworks.csv`이고, 상태 파일을 만들면 같은 사실이 두 곳에 생긴다
(`docs/FE1/ADR-001_같은_사실을_한곳에만_둔다.md`). 그리고 조용히 틀리는 방향이 반대다.
상태가 살아남으면 며칠 전에 끈 작품이 모르는 채로 빠져 시연된다. 사라지면 전부 켜진
상태로 시작하므로 눈에 보이고 바로 되돌릴 수 있다. 계획된 재시작을 위해 `.env`의
`LIVE_OFF_ARTWORKS`만 시작할 때 읽는다.

거르는 자리는 `server/live.py`의 `live(ws)` 안 한 곳이다. 연결마다 `visible()`을 지나므로
모듈 수준 목록이 `app.py`가 주입한 것이든 `live.py`가 스스로 읽은 것이든 상관없다.

이 파일이 하지 않는 일:
- `data/artworks.csv`의 `on_view_status` 열을 읽지 않는다. 그것은 FE3가 적는 현장 확인
  상태이고 운영자의 런타임 토글과 다른 사실이다. 섞으면 둘이 어긋난다.
- `/api/ask`와 `/api/turn`은 거르지 않는다. 끄기는 "인식 후보에서 뺀다"는 정의이고 그 두
  경로는 호출자가 `artwork_id`를 직접 준다.
- BE2의 인식기(`server/artwork_recognizer.py`)가 Live에 붙으면 **후보 목록을 만드는
  자리에서** `visible()`을 지나게 한다. CSV를 읽는 시점에 거르지 않는다.
- `tools/`의 오프라인 실험은 별도 프로세스라 이 상태를 볼 수 없다.
"""
import os

# 꺼진 작품 ID. 비어 있으면 전부 켜진 것이다.
OFF: set[str] = set()


def reset_from_env() -> set[str]:
    """`.env`의 `LIVE_OFF_ARTWORKS`로 상태를 되돌린다. 서버를 켤 때와 시험에서 쓴다."""
    raw = os.environ.get("LIVE_OFF_ARTWORKS") or ""
    OFF.clear()
    OFF.update(part.strip() for part in raw.split(",") if part.strip())
    return set(OFF)


def is_on(artwork_id: str) -> bool:
    return artwork_id not in OFF


def set_on(artwork_id: str, on: bool) -> bool:
    """작품을 켜거나 끈다. 바뀐 경우에만 한 줄 찍고 바뀌었는지 돌려준다."""
    before = is_on(artwork_id)
    if on:
        OFF.discard(artwork_id)
    else:
        OFF.add(artwork_id)
    if before != on:
        print(f"[on_view] {artwork_id} → {'on' if on else 'off'} (꺼진 작품 {len(OFF)}점)")
    return before != on


def visible(artworks: dict) -> dict:
    """꺼진 작품을 뺀 새 목록. 받은 목록을 고치지 않는다."""
    return {key: value for key, value in artworks.items() if is_on(key)}


def rows(artworks: dict) -> list[dict]:
    """운영 화면이 쓸 목록. 켜짐·꺼짐을 함께 돌려준다."""
    return [{"artwork_id": key, "title_en": value.get("title_en", ""), "on_view": is_on(key)}
            for key, value in sorted(artworks.items())]


reset_from_env()
if OFF:
    print(f"[on_view] .env의 LIVE_OFF_ARTWORKS로 {len(OFF)}점을 끈 상태로 시작한다: "
          f"{', '.join(sorted(OFF))}")
