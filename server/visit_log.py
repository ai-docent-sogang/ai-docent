"""Live 관람 이벤트의 JSONL 기록 (담당 FE1, `docs/FE1/관람기록_설계.md`).

기록은 기본적으로 꺼져 있다. `LIVE_VISIT_LOG=visitor`는 박물관 협의 후 사용한다.
음성·프레임·대화 원문·서버 세션 ID·국적·연령대·IP·기기 정보는 저장하지 않는다.
절대 시각은 관람 시작 시각을 10분 단위로 기록한다.

`logs/visits-YYYYMMDD.jsonl`은 Git에서 제외한다. 기록을 시작할 때
`LIVE_VISIT_KEEP_DAYS`(기본 30일)보다 오래된 파일을 정리한다.

미리 보기: `uv run python -m server.visit_log`
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODES = ("off", "team", "visitor")
SOURCE_KINDS = ("mock", "team_rehearsal", "team_shoot", "visitor")
# 측정 계획의 team_filming을 허용해 촬영 기록이 리허설로 분류되지 않게 한다.
SOURCE_KIND_ALIASES = {"team_filming": "team_shoot", "shoot": "team_shoot",
                       "rehearsal": "team_rehearsal"}
START_BUCKET_MINUTES = 10   # 시각을 범주화해 재식별 가능성을 줄인다.
DURATION_BUCKET_S = 10
MAX_TEXT = 64               # 받아쓰기가 실수로 섞이는 것을 줄인다.

# 이벤트별 허용 필드는 설계 문서의 수집 항목과 일치시킨다.
ALLOWED: dict[str, set[str]] = {
    "visit_start": {"start_bucket", "season_id", "gallery", "ui_lang", "mode", "model", "voice"},
    "artwork_identified": {"artwork_id", "via"},
    "artwork_unknown": {"via"},
    "question": {"artwork_id", "channel", "label", "outcome", "first_audio_ms"},
    "comparison": {"artwork_id", "comparison_id", "via"},
    "quality": {"issue", "kept_conversation"},
    # 작품별 사용량을 집계한다. 인사 등 작품이 정해지지 않은 턴은 작품 ID를 비운다.
    "usage": {"artwork_id", "input_audio", "input_image", "input_text", "output_audio", "total"},
    "visit_end": {"reason", "duration_s", "counts"},
}
QUALITY_ISSUES = ("interrupted", "reconnect", "resumed", "phone_idle_close")


class FieldNotAllowed(ValueError):
    """허용되지 않은 이벤트·필드·값을 거부한다."""


def _check(kind: str, fields: dict) -> dict:
    allowed = ALLOWED.get(kind)
    if allowed is None:
        raise FieldNotAllowed(f"모르는 사건: {kind}")
    extra = set(fields) - allowed
    if extra:
        raise FieldNotAllowed(f"{kind}에 없는 칸: {sorted(extra)} (설계: docs/FE1/관람기록_설계.md)")
    if kind == "quality" and fields.get("issue") not in QUALITY_ISSUES:
        raise FieldNotAllowed(f"quality.issue는 {QUALITY_ISSUES} 중 하나여야 한다: {fields.get('issue')!r}")
    for name, value in fields.items():
        if isinstance(value, str) and len(value) > MAX_TEXT:
            raise FieldNotAllowed(
                f"{kind}.{name}이 {MAX_TEXT}자를 넘는다({len(value)}자). 들은 말·한 말은 남기지 않는다")
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str) and len(v) > MAX_TEXT:
                    raise FieldNotAllowed(f"{kind}.{name}.{k}가 {MAX_TEXT}자를 넘는다")
    return fields


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


def _mode() -> str:
    value = _env("LIVE_VISIT_LOG", "off").lower()
    if value not in MODES:
        print(f"[visit_log] LIVE_VISIT_LOG={value!r}는 {MODES} 중에 없다. 기록을 끈다")
        return "off"
    return value


def _source_kind(mode: str) -> str:
    if mode == "visitor":
        return "visitor"
    value = _env("LIVE_VISIT_SOURCE_KIND")
    value = SOURCE_KIND_ALIASES.get(value, value)
    if value in SOURCE_KINDS:
        return value
    if value:
        print(f"[visit_log] LIVE_VISIT_SOURCE_KIND={value!r}는 {SOURCE_KINDS} 중에 없다. team_rehearsal로 둔다")
    return "team_rehearsal"


def _keep_days() -> int:
    raw = _env("LIVE_VISIT_KEEP_DAYS", "30")
    try:
        days = int(raw)
    except ValueError:
        print(f"[visit_log] LIVE_VISIT_KEEP_DAYS={raw!r}를 숫자로 읽지 못했다. 30일로 둔다")
        return 30
    return days if days > 0 else 30


def _dir() -> Path:
    return Path(_env("LIVE_VISIT_DIR") or (ROOT / "logs"))


def start_bucket(now: float) -> str:
    """관람 시작 시각을 10분 단위로 내림한다."""
    dt = datetime.fromtimestamp(now).replace(second=0, microsecond=0)
    return dt.replace(minute=dt.minute - dt.minute % START_BUCKET_MINUTES).isoformat(timespec="minutes")


def purge_old(folder: Path, keep_days: int, now: float) -> list[str]:
    """보관 기간이 지난 파일을 지우고 파일명 목록을 반환한다."""
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=keep_days)).strftime("%Y%m%d")
    gone = []
    for path in sorted(folder.glob("visits-*.jsonl")):
        day = path.stem.removeprefix("visits-")
        if len(day) == 8 and day.isdigit() and day < cutoff:
            path.unlink()
            gone.append(path.name)
    return gone


def usage_fields(meta) -> dict:
    """Gemini의 사용량을 입출력 유형별 토큰 수로 변환한다.

    누락값은 0을 사용한다. 유형별 합은 생각 토큰 등으로 인해 총 토큰 수와 다를 수 있다.
    """
    out = {"input_audio": 0, "input_image": 0, "input_text": 0, "output_audio": 0, "total": 0}
    if meta is None:
        return out
    out["total"] = int(getattr(meta, "total_token_count", 0) or 0)
    for details, prefix in ((getattr(meta, "prompt_tokens_details", None), "input"),
                            (getattr(meta, "response_tokens_details", None), "output")):
        for item in details or ():
            modality = getattr(item, "modality", None)
            name = str(getattr(modality, "name", modality) or "").lower()
            key = f"{prefix}_{name}"
            if key in out:
                out[key] += int(getattr(item, "token_count", 0) or 0)
    return out


class NullLog:
    """기록 비활성 상태의 기록기."""

    on = False
    visit_id = ""

    def event(self, kind: str, **fields) -> None:
        pass

    def end(self, reason: str = "") -> None:
        pass


class VisitLog:
    """관람 한 건의 이벤트를 JSONL에 추가한다."""

    on = True

    def __init__(self, folder: Path, source_kind: str, clock=time.time):
        self._folder = folder
        self._clock = clock
        self._started = clock()
        self._source_kind = source_kind
        self._counts: dict[str, int] = {}
        self._ended = False
        self.visit_id = secrets.token_hex(8)

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def event(self, kind: str, **fields) -> None:
        if self._ended:
            return
        self._write(kind, _check(kind, fields))

    def end(self, reason: str = "") -> None:
        if self._ended:
            return
        elapsed = self._clock() - self._started
        self._write("visit_end", _check("visit_end", {
            "reason": reason,
            "duration_s": int(elapsed // DURATION_BUCKET_S) * DURATION_BUCKET_S,
            "counts": self.counts,
        }))
        self._ended = True

    def _write(self, kind: str, fields: dict) -> None:
        self._counts[kind] = self._counts.get(kind, 0) + 1
        line = {"visit_id": self.visit_id, "t": round(self._clock() - self._started, 1),
                "source_kind": self._source_kind, "event": kind, **fields}
        day = datetime.fromtimestamp(self._clock()).strftime("%Y%m%d")
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            with (self._folder / f"visits-{day}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:
            # 기록 실패로 관람을 중단하지 않고 첫 실패만 알린다.
            if not getattr(self, "_warned", False):
                print(f"[visit_log] 기록을 쓰지 못했다({exc}). 관람은 그대로 이어 간다")
                self._warned = True


def start(*, mode: str, model: str, voice: str, ui_lang: str = "en", clock=time.time):
    """관람 기록을 시작한다. 기록을 사용할 수 없으면 `NullLog`를 반환한다."""
    log_mode = _mode()
    if log_mode == "off":
        return NullLog()
    folder = _dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        gone = purge_old(folder, _keep_days(), clock())
        if gone:
            print(f"[visit_log] 보관 기간이 지난 기록 {len(gone)}개를 지웠다: {', '.join(gone)}")
    except OSError as exc:
        print(f"[visit_log] 기록 폴더를 쓰지 못했다({exc}). 기록을 끈다")
        return NullLog()
    log = VisitLog(folder, _source_kind(log_mode), clock=clock)
    log.event("visit_start", start_bucket=start_bucket(clock()), season_id=_env("LIVE_VISIT_SEASON"),
              gallery=_env("LIVE_VISIT_GALLERY"), ui_lang=ui_lang, mode=mode, model=model, voice=voice)
    return log


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(LIVE_VISIT_LOG="team", LIVE_VISIT_SOURCE_KIND="mock", LIVE_VISIT_DIR=tmp)
        log = start(mode="handsfree", model="gemini-3.8-live", voice="Kore")
        log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
        log.event("question", artwork_id="KHD_SSIREUM", channel="voice", label="", outcome="",
                  first_audio_ms=1659)
        log.event("comparison", artwork_id="KHD_SSIREUM", comparison_id="C_KHD_BRUEGEL", via="function")
        log.event("usage", input_audio=1200, input_image=800, input_text=40, output_audio=950, total=2990)
        log.event("quality", issue="interrupted")
        log.end(reason="phone_closed")
        for path in Path(tmp).glob("visits-*.jsonl"):
            print(f"--- {path.name}")
            print(path.read_text(encoding="utf-8").rstrip())
