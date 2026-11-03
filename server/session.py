"""관람객 한 명의 관람 한 번(세션)을 기억하는 파일.

담당: BE1
같이 보는 파일: app.py (세션을 만들고 갱신함), gemini_client.py (세션 내용을 Gemini에 보냄)

기억하는 것: 프로필(출신 국가·익숙한 미술·설명 길이), 지금 보는 작품, 이미 본 작품, 이미 쓴 비교쌍, 최근 대화.
모두 서버 메모리에만 있다. 서버를 끄거나 세션을 끝내면 사라지고 파일로 저장하지 않는다(개인정보 원칙).
"""

import uuid
from dataclasses import dataclass, field

# 최근 대화를 몇 번까지 기억할지. 너무 많으면 Gemini에 보내는 글이 길어져 느려지고 비용이 늘고,
# 너무 적으면 "아까 말한 그 그림" 같은 앞 대화를 잊는다. 실측 후 조정한다.
MAX_HISTORY_TURNS = 8


@dataclass
class Session:
    session_id: str
    profile: dict = field(default_factory=lambda: {"country": "", "familiar_art": [], "depth": ""})
    current_artwork_id: str = ""
    seen_artwork_ids: list = field(default_factory=list)
    used_comparison_ids: list = field(default_factory=list)  # 같은 비교를 반복하지 않으려고 기록
    history: list = field(default_factory=list)  # [{"visitor": 관람객 말, "docent": 도슨트 답}, ...]

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
    return _sessions.get(session_id)


def end_session(session_id):
    _sessions.pop(session_id, None)
