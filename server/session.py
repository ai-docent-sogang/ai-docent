"""관람 세션 상태를 메모리에만 보관한다. 서버를 끄거나 세션을 끝내면 사라진다."""

import uuid
from dataclasses import dataclass, field

MAX_HISTORY_TURNS = 8


@dataclass
class Session:
    session_id: str
    profile: dict = field(default_factory=lambda: {"country": "", "familiar_art": [], "depth": ""})
    current_artwork_id: str = ""
    seen_artwork_ids: list = field(default_factory=list)
    used_comparison_ids: list = field(default_factory=list)
    history: list = field(default_factory=list)  # [{"visitor": ..., "docent": ...}]

    def apply_profile_update(self, update):
        if update.country:
            self.profile["country"] = update.country
        for art in update.familiar_art:
            if art and art not in self.profile["familiar_art"]:
                self.profile["familiar_art"].append(art)
        if update.depth:
            self.profile["depth"] = update.depth

    def record_turn(self, visitor_text, reply):
        if reply.artwork_id and reply.artwork_id != "unknown":
            self.current_artwork_id = reply.artwork_id
            if reply.artwork_id not in self.seen_artwork_ids:
                self.seen_artwork_ids.append(reply.artwork_id)
        if reply.comparison_id and reply.comparison_id not in self.used_comparison_ids:
            self.used_comparison_ids.append(reply.comparison_id)
        self.history.append({"visitor": visitor_text, "docent": reply.reply})
        del self.history[:-MAX_HISTORY_TURNS]


_sessions = {}


def create_session():
    session = Session(session_id=uuid.uuid4().hex)
    _sessions[session.session_id] = session
    return session


def get_session(session_id):
    return _sessions.get(session_id)


def end_session(session_id):
    _sessions.pop(session_id, None)
