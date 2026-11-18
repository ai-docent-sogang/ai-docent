"""관람 한 번의 턴 기억·작품/비교 함수 응답·관람 기록. 담당: FE1.

소켓과 재연결은 live.py가 관리한다. 이 객체는 연결마다 하나씩 만들고,
화면에 보낼 결과는 to_browser 큐에 넣는다. 음성·프레임은 저장하지 않는다.
"""
import asyncio
import time
from types import SimpleNamespace

from .ask import build_artwork_context
from .content import rank_comparisons
from .live_config import UNKNOWN
from .live_context import MAX_COMPARISON_OPTIONS, REGION_TAGS, comparison_block, home_of
from .live_transcript import comparison_in_transcript


def comparison_display(comparison_id, verified_comparisons):
    """비교 하나를 화면이 그리는 데 필요한 값만. 없는 ID면 빈 dict.

    화면(static/app.js)이 같은 값을 손으로 베껴 두고 있었는데, 예원님이 `data/comparisons.csv`를
    늘릴 때마다 어긋났다(11/18에 7→20점이 되면서 14개가 요약에서 사라지고 ID 하나는 죽었다).
    베낀 목록을 지우려고 서버가 보내 준다. angle·similarities·differences는 보내지 않는다 —
    그것은 Gemini에게 주는 설명 재료이고 화면은 쓰지 않는다.
    """
    pair = verified_comparisons.get(comparison_id)
    if pair is None:
        return {}
    return {"foreign_title": pair["foreign_title"], "foreign_artist": pair["foreign_artist"],
            "foreign_collection": pair["foreign_collection"], "foreign_url": pair["foreign_url"]}


def ranked_comparison_ids(artwork_id, profile, used_ids, verified_comparisons):
    """comparison_block이 적는 후보와 같은 순서의 comparison_id 목록.

    comparison_block(BE1)의 글에는 ID가 없어서 모델이 report_comparison에 넣을 값을 모른다.
    BE1 파일을 고치지 않으려고 같은 정렬(rank_comparisons + REGION_TAGS + 최대 개수)을 여기서 다시 부른다.
    live_context.comparison_block의 정렬을 바꾸면 여기도 함께 고친다.
    """
    # BE1의 home_of를 쓴다. 전에는 country만 읽어서, 프로필에 region만 들어오면 BE1의 글 순서와
    # 이 ID 순서가 어긋났다(11/18 확인: region=japan이면 글은 Sumo가 1번, ID는 Bruegel이 1번).
    # 모델은 글의 "option 1"을 보고 같은 자리의 ID를 넣으므로, 말한 비교와 기록된 비교가 달라진다.
    country = home_of(profile).lower()
    ranking_profile = {"country": country, "familiar_art": REGION_TAGS.get(country, [])}
    ranked = rank_comparisons(list(verified_comparisons.values()), artwork_id, ranking_profile,
                              set(used_ids))[:MAX_COMPARISON_OPTIONS]
    return [c["comparison_id"] for c in ranked]


class LiveConversation:
    def __init__(self, *, mode, artwork_id, profile, visit, artworks, comparisons,
                 resume_store, vlog, saved=None):
        self.mode = mode
        self.profile = profile
        self.visit = visit
        self.artworks = artworks
        self.comparisons = comparisons
        # app.py가 주입한 목록에서 한 번만 거른다. 도구 선언·함수 결과·화면이 함께 쓴다.
        self.verified_comparisons = {
            c["comparison_id"]: c for c in comparisons
            if c.get("verification_status", "").strip().lower() == "verified"}
        self.resume_store = resume_store
        self.vlog = vlog
        # 느린 폰 전송이 Gemini 읽기를 막지 않게 소켓 중계가 이 큐를 따로 비운다.
        self.to_browser = asyncio.Queue()
        # 지금 연결된 Live 세션과 재개 핸들. 재연결하면 session만 바뀌고 폰과의 연결은 그대로 둔다.
        #   turn_open: 답변을 내보내는 중인지. 답변 도중에 연결이 옮겨 가면 폰은 turn_complete를
        #              받지 못해 버튼이 잠긴 채로 남는다. 그래서 옮기기 전에 턴을 닫아 준다.
        #   heard/said: 이번 턴의 질문과 답을 모아 둔다. 턴이 끝나면 관람 기억에 넣는다.
        #   artwork_id: 지금 보는 작품. push는 연결할 때 고정, handsfree는 report_current_artwork로 바뀐다.
        #   comparison_id: 이번 턴에 report_comparison으로 보고된 비교(handsfree만). 기록하면 비운다.
        self.state = {"session": None, "handle": saved["handle"] if saved else None, "turn_open": False,
                 "heard": "", "said": "",
                 "artwork_id": artwork_id, "comparison_id": "",
                 # 폰이 마지막으로 무언가 보낸 시각(죽은 연결 판단, handsfree)
                 "last_input": time.monotonic(),
                 # on_speech 정책: 들고 있는 최신 사진, 이 Gemini 연결에서 첫 사진을 넘겼는지
                 "latest_frame": None, "first_frame_sent": False, "turn_frame_sent": False,
                 # 이번 턴에 report_comparison이 불렸는지(받아쓰기로 비교를 찾을지 정할 때 쓴다)
                 "comparison_called": False,
                 # 받아쓰기 거르기: 아직 들고 있는 꼬리, 걸러 낸 모델 속 글(턴이 끝나면 로그에 적는다)
                 "said_hold": "", "said_leak": "",
                 # 인사 턴이 아직 끝나지 않았다(handsfree). 그동안 사진은 들고만 있는다.
                 "opening_turn": False,
                 # 관람 기록용. heard_at: 이번 턴에 질문이 들어온 마지막 시각(받아쓰기 조각 또는 글).
                 # first_audio_at: 이번 턴의 첫 답변 소리가 나간 시각. 둘의 차이가 first_audio_ms다.
                 # channel: 이번 턴을 글로 물었는지 말로 물었는지. usage: 이번 턴의 마지막 사용량.
                 # usage_seen: 지금까지 Gemini가 알려 준 누적 사용량(11/18 실측으로 누적임을 확인).
                 "heard_at": None, "first_audio_at": None, "channel": "", "usage": None,
                 "usage_seen": {}, "speech_end_at": None}

    def push_said(self, text):
        """걸러 낸 뒤 남은 답변 받아쓰기를 폰에 보내고 관람 기억에 쌓는다."""
        if text:
            self.state["said"] += text
            self.to_browser.put_nowait(("text", {"type": "said", "text": text}))

    def save_resume(self):
        """재개 핸들·지금 작품을 저장소에 남긴다. 폰 WS가 끊겨도 다음 연결이 이어 쓴다."""
        if self.state["handle"] or self.state["artwork_id"]:
            self.resume_store[self.visit.session_id] = {
                "handle": self.state["handle"], "artwork_id": self.state["artwork_id"],
                "updated": time.time()}

    def first_audio_ms(self):
        """관람객이 말을 멈춘 뒤 첫 답변 소리가 나갈 때까지의 밀리초. 못 재면 -1.

        기준은 Gemini가 "말이 끝났다"고 알려 준 시각(voice_activity)이고, 그 신호가 없으면
        이번 턴에 마지막으로 받은 받아쓰기 조각의 시각을 쓴다. 받아쓰기는 늦게 오므로 답변이
        그보다 먼저 시작되는 일이 있다 — 11/18 실측에서 그렇게 해서 123ms라는 거짓 값이 나왔다.
        그런 턴은 잴 수 없는 것으로 보고 -1을 적는다. 작은 수를 적으면 평균이 거짓이 된다.

        **이 숫자는 관람객이 기다린 시간보다 작다.** 11/18 실측에서 voice_activity 신호는
        한 번도 오지 않았고(두 번의 왕복, 0건), 그래서 늘 받아쓰기를 기준으로 쓴다. 같은 턴을
        폰 쪽에서 재면 943ms/1646ms인 것이 1932ms/2481ms였다 — 약 1초 낮게 나온다. 턴 사이를
        견주는 데는 쓸 수 있지만, "관람객이 몇 초 기다렸다"로 말하면 안 된다. 제대로 재려면
        voice_activity가 오게 되거나(Google 쪽), 폰이 말이 끝난 시각을 보내 줘야 한다.
        """
        audio_at = self.state["first_audio_at"]
        base = self.state["speech_end_at"] or self.state["heard_at"]
        if not base or not audio_at:
            return -1
        gap_ms = int((audio_at - base) * 1000)
        # 받아쓰기를 기준으로 쓴 턴에서 간격이 비현실적으로 짧으면(받아쓰기가 답보다 늦게 온 것)
        # 잴 수 없는 것으로 둔다. 실측에서 함수를 거치지 않는 턴도 1.2초 아래로 내려가지 않았다.
        if self.state["speech_end_at"] is None and gap_ms < 300:
            return -1
        return gap_ms

    def remember_turn(self):
        """이번 턴을 관람 기억에 넣는다. BE1의 session.record_turn을 부르기만 한다.

        push는 comparison_id가 늘 빈 값이다(음성 답에서 어떤 비교를 썼는지 알 수 없다. 추측하지 않는다).
        handsfree는 이번 턴에 Live가 report_comparison으로 보고한 값을 넘긴다.
        """
        said = self.state["said"].strip()
        if not said:
            return
        if (self.mode == "handsfree" and not self.state["comparison_called"]
                and self.state["artwork_id"] in self.artworks):
            # Live가 함수를 부르지 않고 비교를 말한 턴. 답에 지금 작품의 비교쌍 제목이 나오면 같은 처리를 한다.
            cid = comparison_in_transcript(said, self.state["artwork_id"], self.verified_comparisons)
            if cid and cid not in self.visit.used_comparison_ids:
                print(f"[live] 함수 없이 말한 비교를 받아쓰기에서 찾음: {cid}")
                self.state["comparison_id"] = cid
                self.to_browser.put_nowait(("text", {
                    "type": "comparison", "comparison_id": cid, "artwork_id": self.state["artwork_id"],
                    "source": "transcript", **comparison_display(cid, self.verified_comparisons)}))
                self.vlog.event("comparison", artwork_id=self.state["artwork_id"], comparison_id=cid,
                                via="transcript")
        self.visit.record_turn(self.state["heard"].strip(), SimpleNamespace(
            artwork_id=self.state["artwork_id"], comparison_id=self.state["comparison_id"], reply=said))
        # 관람 기록: 질문 한 번. 글자는 넣지 않는다(기록 모듈이 거부한다).
        # 관람객이 아무 말도 하지 않은 턴(연결 직후 인사)은 질문으로 세지 않는다.
        # label·outcome은 아직 빈 값이다 — 라벨 체계(FE3)와 no_source 판정(BE1)을 정해야 채운다.
        if self.state["heard"].strip():
            self.vlog.event("question", artwork_id=self.state["artwork_id"],
                            channel=self.state["channel"] or "voice", label="", outcome="",
                            first_audio_ms=self.first_audio_ms())
        self.state["heard"] = self.state["said"] = self.state["comparison_id"] = ""
        self.state["comparison_called"] = False
        self.state["heard_at"] = self.state["first_audio_at"] = self.state["speech_end_at"] = None
        self.state["channel"] = ""

    def answer_tool_call(self, call):
        """Live의 함수 호출 하나에 돌려줄 결과를 만들고, 폰에 알릴 것이 있으면 줄에 넣는다."""
        args = call.args or {}
        if call.name == "report_current_artwork":
            artwork_id = str(args.get("artwork_id") or "")
            found = self.artworks.get(artwork_id)
            if found is None:
                # unknown이거나 목록 밖의 값. 지금 작품을 지우지 않는다(잠깐 다른 곳을 비춘 경우).
                self.vlog.event("artwork_unknown", via="function")
                return {"artwork_id": UNKNOWN,
                        "instruction": "You cannot tell which painting is in view. Do not describe any "
                                       "painting. Kindly ask the visitor to point the camera at the painting."}
            self.state["artwork_id"] = artwork_id
            self.vlog.event("artwork_identified", artwork_id=artwork_id, via="function")
            self.save_resume()
            used = list(self.visit.used_comparison_ids)
            if self.state["comparison_id"]:
                used.append(self.state["comparison_id"])
            # 화면이 작품 목록을 베껴 두지 않게 보여 줄 값을 같이 보낸다(11/18). 베낀 목록은
            # 예원님이 CSV를 늘릴 때마다 어긋났다 — 하루에 두 번 났다.
            self.to_browser.put_nowait(("text", {
                "type": "artwork", "artwork_id": artwork_id, "artwork_title": found["title_en"],
                "artist": found.get("artist", "")}))
            return {
                "artwork_id": artwork_id,
                "artwork": build_artwork_context(found),
                "comparison_options": comparison_block(self.comparisons, artwork_id, self.profile, used),
                # comparison_options와 같은 순서. report_comparison에 넣을 값이다.
                "comparison_ids": ranked_comparison_ids(
                    artwork_id, self.profile, used, self.verified_comparisons),
            }
        if call.name == "report_comparison":
            self.state["comparison_called"] = True   # 이 턴은 받아쓰기로 비교를 찾지 않는다
            comparison_id = str(args.get("comparison_id") or "")
            pair = self.verified_comparisons.get(comparison_id)
            if pair is None or pair["artwork_id"] != self.state["artwork_id"]:
                valid = [cid for cid, c in self.verified_comparisons.items()
                         if c["artwork_id"] == self.state["artwork_id"]]
                return {"ok": False,
                        "error": f"{comparison_id} is not a verified comparison for the current artwork "
                                 f"({self.state['artwork_id'] or 'none reported yet'}). Valid ids: {valid}. "
                                 "Do not make this comparison."}
            self.state["comparison_id"] = comparison_id
            self.to_browser.put_nowait(("text", {
                "type": "comparison", "comparison_id": comparison_id, "artwork_id": pair["artwork_id"],
                "source": "function",
                **comparison_display(comparison_id, self.verified_comparisons)}))
            self.vlog.event("comparison", artwork_id=pair["artwork_id"], comparison_id=comparison_id,
                            via="function")
            return {"ok": True, "comparison_id": comparison_id,
                    "foreign_painting": f"{pair['foreign_title']} by {pair['foreign_artist']} "
                                        f"({pair['foreign_date']}, {pair['foreign_collection']})",
                    "angle": pair["angle"], "similarities": pair["similarities"],
                    "differences": pair["differences"]}
        return {"ok": False, "error": f"unknown function {call.name}"}

