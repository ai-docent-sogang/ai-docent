"""운영자용 라우터 (담당 FE1). 관람객 화면이 아니다(관람객 화면은 `/`).

- `GET  /api/ops/stats`                   관람 기록 집계
- `GET  /api/ops/artworks`                작품 목록과 켜짐·꺼짐
- `POST /api/ops/artworks/{id}/on_view`   작품을 켜고 끈다

화면(`/ops`)은 다음 커밋에서 더한다.

집계 수식은 `server/visit_stats.py`에 있고, 켜기/끄기 상태는 `server/on_view.py`에 있다.
이 파일은 라우팅과 입력 검사, 작품 제목 붙이기만 한다.

**인증이 없다.** `POST`는 상태를 바꾸므로 주소를 아는 사람이 작품을 끌 수 있다. 그래서
공개 주소(cloudflared 등)로 서버를 열 때는 운영 페이지를 쓰지 않는다. 시연 체크리스트에
적어 두었다. 이 전제가 바뀌면 토큰을 먼저 넣어야 한다.
"""
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import on_view, visit_stats

router = APIRouter()

# app.py에서 읽은 작품 목록을 공유한다.
artworks = {}


class OnViewRequest(BaseModel):
    on_view: bool


@router.get("/api/ops/stats")
def ops_stats(from_day: str = "", to_day: str = "", source_kind: str = "team_rehearsal"):
    """관람 기록을 집계해 돌려준다. 형식은 docs/api.md 참고.

    받는 값(쿼리): from_day·to_day(YYYY-MM-DD, 비우면 오늘 하루),
    source_kind(기본 team_rehearsal. 한 종류만. 모의와 실측을 합산하지 않는다)
    돌려주는 값: visit_stats.collect()의 결과에 작품 제목과 켜짐·꺼짐, 기록이 없는 작품 목록
    오류: 400 날짜 형식·기간 역순·모르는 source_kind
    """
    today = date.today().isoformat()
    try:
        out = visit_stats.collect(from_day or today, to_day or today, source_kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    seen = set()
    for row in out["artworks"]:
        artwork = artworks.get(row["artwork_id"]) or {}
        row["title_en"] = artwork.get("title_en", "")
        row["on_view"] = on_view.is_on(row["artwork_id"])
        seen.add(row["artwork_id"])
    # 아무도 묻지 않은 작품도 콘텐츠 공백의 신호다. 0으로 채우지 않고 ID만 따로 알린다.
    out["artworks_without_records"] = sorted(set(artworks) - seen)
    return out


@router.get("/api/ops/artworks")
def ops_artworks():
    """작품 목록과 켜짐·꺼짐. 형식은 docs/api.md 참고.

    돌려주는 값: artworks(작품 ID·제목·on_view), off(꺼진 작품 ID), note(재시작하면 초기화)
    """
    return {"artworks": on_view.rows(artworks), "off": sorted(on_view.OFF),
            "note": "서버를 다시 켜면 .env의 LIVE_OFF_ARTWORKS만 남고 나머지는 모두 켜진다"}


@router.post("/api/ops/artworks/{artwork_id}/on_view")
def ops_set_on_view(artwork_id: str, body: OnViewRequest):
    """작품을 켜거나 끈다. 형식은 docs/api.md 참고.

    받는 값: 경로의 artwork_id, 본문 {"on_view": true|false}
    돌려주는 값: changed(실제로 바뀌었는지)와 /api/ops/artworks와 같은 목록
    오류: 404 모르는 artwork_id
    """
    if artwork_id not in artworks:
        raise HTTPException(404, "artwork not found")
    changed = on_view.set_on(artwork_id, body.on_view)
    return {"changed": changed, **ops_artworks()}
