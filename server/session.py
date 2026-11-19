"""관람 세션의 프로필·작품·비교·최근 대화 기억. 담당: BE1.

상태는 서버 메모리에만 보관하며 관람 종료 또는 비활성 만료 시 폐기한다.
"""

import time
import uuid
from dataclasses import dataclass, field

# Gemini에 전달할 최근 대화 수.
MAX_HISTORY_TURNS = 8


@dataclass
class Session:
    session_id: str
    profile: dict = field(default_factory=lambda: {"country": "", "familiar_art": [], "depth": ""})
    current_artwork_id: str = ""
    seen_artwork_ids: list = field(default_factory=list)
    used_comparison_ids: list = field(default_factory=list)  # 같은 비교를 반복하지 않으려고 기록
    history: list = field(default_factory=list)  # [{"visitor": 관람객 말, "docent": 도슨트 답}, ...]
    last_active_at: float = field(default_factory=time.monotonic, repr=False)

    def touch(self):
        self.last_active_at = time.monotonic()

    def apply_profile_update(self, update):
        """이번 대화에서 새로 알게 된 프로필만 덧붙인다. 빈 값은 기존 값을 지우지 않는다."""
        if update.country:
            self.profile["country"] = update.country
        for art in update.familiar_art:
            if art and art not in self.profile["familiar_art"]:
                self.profile["familiar_art"].append(art)
        if update.depth:
            self.profile["depth"] = update.depth

    def record_turn(self, visitor_text, reply):
        """대화 한 번의 결과를 기록한다: 인식된 작품, 사용한 비교쌍, 대화 내용(최근 것만 유지)."""
        self.touch()
        if reply.artwork_id and reply.artwork_id != "unknown":
            self.current_artwork_id = reply.artwork_id
            if reply.artwork_id not in self.seen_artwork_ids:
                self.seen_artwork_ids.append(reply.artwork_id)
        if reply.comparison_id and reply.comparison_id not in self.used_comparison_ids:
            self.used_comparison_ids.append(reply.comparison_id)
        self.history.append({"visitor": visitor_text, "docent": reply.reply})
        del self.history[:-MAX_HISTORY_TURNS]  # 마지막 MAX_HISTORY_TURNS개만 남긴다


# 진행 중인 모든 세션. 키는 session_id. 서버 한 대, 시연용이라 데이터베이스 없이 메모리에 둔다.
_sessions = {}


def create_session():
    session = Session(session_id=uuid.uuid4().hex)
    _sessions[session.session_id] = session
    return session


def get_session(session_id):
    """없는 ID면 None을 돌려준다(서버를 다시 켜면 이전 세션은 모두 없어진다)."""
    session = _sessions.get(session_id)
    if session is not None:
        session.touch()
    return session


def end_session(session_id):
    _sessions.pop(session_id, None)


def expire_idle_sessions(max_idle_s, active_ids=()):
    """접속 중인 관람은 보호하고, 오래 방치된 관람 기억을 폐기한다."""
    cutoff = time.monotonic() - max_idle_s
    expired = [sid for sid, session in list(_sessions.items())
               if sid not in active_ids and session.last_active_at < cutoff]
    for sid in expired:
        end_session(sid)
    return expired
