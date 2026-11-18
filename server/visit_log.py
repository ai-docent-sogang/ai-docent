"""관람 기록 — Live 대화에서 일어난 일을 사건 한 줄씩 남긴다.

담당: FE1
설계: docs/FE1/관람기록_설계.md (11/18). 같이 보는 파일: server/live.py (사건이 생기는 곳)

**기본값은 꺼짐이다.** `LIVE_VISIT_LOG`가 `team`이나 `visitor`일 때만 파일을 만든다.
실제 관람객 대상(`visitor`)은 박물관 협의 뒤에만 켠다.

**남기지 않는 것**: 들은 말·한 말의 글자, 소리, 사진, 서버 세션 ID, 국적·연령대,
IP·기기 정보, 벽시계 시각(관람 시작 버킷 외). 이것은 약속이 아니라 코드로 막혀 있다 —
사건마다 넣을 수 있는 칸이 아래 ALLOWED에 적혀 있고, 그 밖의 칸은 거부한다(FieldNotAllowed).
글자 칸도 64자를 넘기면 거부한다. 받아쓰기가 실수로 섞여 들어오는 것을 막기 위해서다.

AGENTS.md: "카메라 프레임과 음성은 처리에만 사용하고 기본적으로 저장하지 않는다."

파일: `logs/visits-YYYYMMDD.jsonl` (한 줄이 사건 하나). `logs/`는 git에서 제외돼 있다.
수집 시각부터 `LIVE_VISIT_KEEP_DAYS`(기본 30)일이 지난 파일은 다음에 켤 때 지운다.

환경 변수:
    LIVE_VISIT_LOG          off(기본) | team | visitor
    LIVE_VISIT_SOURCE_KIND  mock | team_rehearsal | team_shoot | visitor  (team일 때 함께 지정)
    LIVE_VISIT_SEASON       전시 회차 값. 비우면 "" (설계의 season_id)
    LIVE_VISIT_GALLERY      전시실 값. 비우면 ""
    LIVE_VISIT_DIR          기록 폴더. 비우면 저장소의 logs/
    LIVE_VISIT_KEEP_DAYS    보관 일수. 기본 30

쓰는 쪽은 켜짐·꺼짐을 신경 쓰지 않는다. 꺼져 있으면 아무것도 하지 않는 기록기를 돌려준다.

    log = visit_log.start(mode="handsfree", model=..., voice=...)
    log.event("artwork_identified", artwork_id="KHD_SSIREUM", via="function")
    log.end(reason="phone_closed")

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
START_BUCKET_MINUTES = 10   # 근거 조사: 분 단위 시각은 재식별 단서가 된다
DURATION_BUCKET_S = 10
MAX_TEXT = 64               # 이보다 긴 글자는 받아쓰기가 섞인 것으로 본다

# 사건마다 넣을 수 있는 칸. 여기 없는 칸은 거부한다. 설계 문서의 "남기는 것" 표와 같아야 한다.
ALLOWED: dict[str, set[str]] = {
    "visit_start": {"start_bucket", "season_id", "gallery", "ui_lang", "mode", "model", "voice"},
    "artwork_identified": {"artwork_id", "via"},
    "artwork_unknown": {"via"},
    "question": {"artwork_id", "channel", "label", "outcome", "first_audio_ms"},
    "comparison": {"artwork_id", "comparison_id", "via"},
    "quality": {"issue", "kept_conversation"},
    "usage": {"input_audio", "input_image", "input_text", "output_audio", "total"},
    "visit_end": {"reason", "duration_s", "counts"},
}
# quality.issue가 가질 수 있는 값. 그 밖은 거부한다.
QUALITY_ISSUES = ("interrupted", "reconnect", "resumed", "phone_idle_close")


class FieldNotAllowed(ValueError):
    """설계에 없는 칸이나 너무 긴 글자를 넣으려 했다. 개인정보 약속을 코드로 지키는 자리다."""


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
    """벽시계 시각을 10분 단위로 버린다. 관람 한 번에 한 번만 남긴다."""
    dt = datetime.fromtimestamp(now).replace(second=0, microsecond=0)
    return dt.replace(minute=dt.minute - dt.minute % START_BUCKET_MINUTES).isoformat(timespec="minutes")


def purge_old(folder: Path, keep_days: int, now: float) -> list[str]:
    """보관 기간이 지난 기록 파일을 지운다. 지운 파일 이름을 돌려준다."""
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=keep_days)).strftime("%Y%m%d")
    gone = []
    for path in sorted(folder.glob("visits-*.jsonl")):
        day = path.stem.removeprefix("visits-")
        if len(day) == 8 and day.isdigit() and day < cutoff:
            path.unlink()
            gone.append(path.name)
    return gone


def usage_fields(meta) -> dict:
    """Gemini의 `usage_metadata` 하나를 `usage` 사건의 칸으로 바꾼다.

    SDK를 부르지 않는다(값만 읽는다). 종류별 숫자는 `prompt_tokens_details`·
    `response_tokens_details`에 `modality`(AUDIO/IMAGE/TEXT)와 `token_count`로 들어 있다.
    없는 값은 0으로 둔다. 종류별 합이 전체와 다를 수 있다(생각 토큰 등은 종류가 없다).
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
    """기록이 꺼져 있을 때. 부르는 쪽이 켜짐·꺼짐을 묻지 않아도 되게 한다."""

    on = False
    visit_id = ""

    def event(self, kind: str, **fields) -> None:
        pass

    def end(self, reason: str = "") -> None:
        pass


class VisitLog:
    """관람 한 번. 사건을 한 줄씩 파일에 덧붙인다."""

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
            # 기록 때문에 관람이 멈추면 안 된다. 한 번 알리고 그 뒤로는 조용히 넘긴다.
            if not getattr(self, "_warned", False):
                print(f"[visit_log] 기록을 쓰지 못했다({exc}). 관람은 그대로 이어 간다")
                self._warned = True


def start(*, mode: str, model: str, voice: str, ui_lang: str = "en", clock=time.time):
    """관람 하나를 시작한다. 꺼져 있으면 아무것도 하지 않는 기록기를 돌려준다."""
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


if __name__ == "__main__":  # 미리 보기: 임시 폴더에 한 관람을 적고 그대로 찍는다
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
