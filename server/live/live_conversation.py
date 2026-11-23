"""관람 한 번의 턴 기억·작품/비교 함수 응답·관람 기록. 담당: FE1.

소켓과 재연결은 live.py가 관리한다. 이 객체는 연결마다 하나씩 만들고,
화면에 보낼 결과는 to_browser 큐에 넣는다. 음성·프레임은 저장하지 않는다.
"""
import asyncio
import time
from types import SimpleNamespace

from .. import session as sessions
from ..content import build_artwork_context, rank_comparisons
from . import live_config
from .live_config import UNKNOWN
from .live_context import MAX_COMPARISON_OPTIONS, REGION_TAGS, comparison_block, home_of
from .live_transcript import comparison_in_transcript
from ..question_labels import normalize_label, normalize_outcome


def comparison_display(comparison_id, verified_comparisons):
    """화면에 필요한 비교 작품 제목·작가·소장처·출처 URL을 반환한다."""
    pair = verified_comparisons.get(comparison_id)
    if pair is None:
        return {}
    return {"foreign_title": pair["foreign_title"], "foreign_artist": pair["foreign_artist"],
            "foreign_collection": pair["foreign_collection"], "foreign_url": pair["foreign_url"]}


def ranked_comparison_ids(artwork_id, profile, used_ids, verified_comparisons):
    """comparison_block과 같은 순서의 비교 ID를 반환한다. 정렬 변경 시 두 함수를 함께 수정한다."""
    # comparison_block과 같은 지역 해석·정렬을 사용해 후보 설명과 ID 순서를 맞춘다.
    country = home_of(profile).lower()
    ranking_profile = {"country": country, "familiar_art": REGION_TAGS.get(country, [])}
    ranked = rank_comparisons(list(verified_comparisons.values()), artwork_id, ranking_profile,
                              set(used_ids))[:MAX_COMPARISON_OPTIONS]
    return [c["comparison_id"] for c in ranked]


def artwork_card(art):
    """작품 사실 없이 누구인지만 알려 주는 카드. per_question에서 사실은 lookup_facts로만 나간다."""
    return (f"ARTWORK: {art['title_en']}\nArtist: {art['artist']}\nDate: {art['date']}\n"
            "Facts are not included. Call lookup_facts when the visitor asks about it.")


class LiveConversation:
    def __init__(self, *, mode, artwork_id, profile, visit, artworks, comparisons,
                 resume_store, vlog, saved=None):
        self.mode = mode
        self.profile = profile
        self.visit = visit
        self.artworks = artworks
        self.comparisons = comparisons
        # app.py가 주입한 목록에서 한 번만 거른다. 도구 선언·함수 결과·화면이 함께 쓴다.
        # artworks는 켜진 작품만 담겨 오므로(server/on_view.py) 끈 작품의 비교쌍도 함께 빠진다.
        self.verified_comparisons = {
            c["comparison_id"]: c for c in comparisons
            if c.get("verification_status", "").strip().lower() == "verified"
            and c.get("artwork_id") in self.artworks}
        self.resume_store = resume_store
        self.vlog = vlog
        # 느린 폰 전송이 Gemini 읽기를 막지 않게 소켓 중계가 이 큐를 따로 비운다.
        self.to_browser = asyncio.Queue()
        # 연결별 상태. 재연결 시 Gemini 세션만 바꾸고 현재 작품과 턴 정보를 유지한다.
        self.state = {"session": None, "handle": saved["handle"] if saved else None, "turn_open": False,
                 "heard": "", "said": "",
                 "artwork_id": artwork_id, "comparison_id": "",
                 # 폰이 마지막으로 무언가 보낸 시각(죽은 연결 판단, handsfree)
                 "last_input": time.monotonic(),
                 # on_speech 정책: 들고 있는 최신 사진, 이 Gemini 연결에서 첫 사진을 넘겼는지
                 "latest_frame": None, "first_frame_sent": False, "turn_frame_sent": False,
                 # 가장 최근 사진(메모리에만). Live가 unknown이라고 할 때 인식 보조가 쓴다.
                 "last_jpeg": None,
                 # 이번 턴에 report_comparison이 불렸는지(받아쓰기로 비교를 찾을지 정할 때 쓴다)
                 "comparison_called": False,
                 # 받아쓰기 거르기: 아직 들고 있는 꼬리, 걸러 낸 모델 속 글(턴이 끝나면 로그에 적는다)
                 "said_hold": "", "said_leak": "",
                 # 인사 턴이 아직 끝나지 않았다(handsfree). 그동안 사진은 들고만 있는다.
                 "opening_turn": False,
                 # 이번 턴에 report_question이 보고한 질문 유형과 답변 결과
                 "label": "", "outcome": "",
                 # 이번 턴에 작품 사실을 실제로 조회했는가. 질문 여부의 기준이다(lookup_facts).
                 "grounded": False,
                 # 질문/첫 음성 시각과 채널, 현재 연결의 누적 사용량을 추적한다.
                 "heard_at": None, "first_audio_at": None, "channel": "", "usage": None,
                 "usage_seen": {}, "speech_end_at": None}

    def push_said(self, text):
        """걸러 낸 뒤 남은 답변 받아쓰기를 폰에 보내고 관람 기억에 쌓는다."""
        if text:
            self.state["said"] += text
            self.to_browser.put_nowait(("text", {"type": "said", "text": text}))

    def save_resume(self):
        """재개 핸들·지금 작품을 저장소에 남긴다. 폰 WS가 끊겨도 다음 연결이 이어 쓴다."""
        if sessions.get_session(self.visit.session_id) is not self.visit:
            return  # END VISIT 이후 늦게 도착한 Gemini 메시지가 기억을 되살리지 않게 한다.
        if self.state["handle"] or self.state["artwork_id"]:
            self.resume_store[self.visit.session_id] = {
                "handle": self.state["handle"], "artwork_id": self.state["artwork_id"],
                "updated": time.time()}

    def first_audio_ms(self):
        """질문 종료 추정 시각부터 첫 음성까지의 간격(ms). 측정 불가 시 -1.

발화 종료 신호가 없으면 마지막 받아쓰기 시각을 사용한다. 이 값은 실제 대기 시간보다 짧다.
받아쓰기가 늦게 도착해 간격이 300ms 미만이면 측정값을 버린다.
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
        """완료된 답변과 작품·비교 정보를 관람 기억에 반영하고 질문 횟수를 기록한다."""
        said = self.state["said"].strip()
        if not said:
            # 라벨을 여기서 비우지 않는다. 실제 Gemini는 함수를 부른 직후 말 없는 turn_complete를 먼저
            # 보내고 답변은 그 뒤에 온다(11/20 실측: 호출 33.31초, 답변 음성 33~34초, 답변 끝 39.3초).
            # 이 자리에서 비우면 방금 적은 라벨과 grounded가 답변 턴에 닿기 전에 사라진다.
            # 한계: 추임새에 함수를 부르고 침묵하면 그 라벨이 다음 질문에 붙을 수 있다.
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
        # 말을 한 턴은 모두 기록하되, 사실을 조회한 턴만 grounded=True다. 질문 수는 그 턴만 센다.
        # 라벨·결과는 Live가 보고한 값만 쓰고 답변 글에서 추론하지 않는다(docs/FE1/관람기록_설계.md).
        if self.state["heard"].strip():
            self.vlog.event("question", artwork_id=self.state["artwork_id"],
                            channel=self.state["channel"] or "voice",
                            label=self.state["label"] or "unknown",
                            outcome=self.state["outcome"] or "unknown",
                            grounded=self.state["grounded"],
                            first_audio_ms=self.first_audio_ms())
        self.state["label"] = self.state["outcome"] = ""
        self.state["grounded"] = False
        self.state["heard"] = self.state["said"] = self.state["comparison_id"] = ""
        self.state["comparison_called"] = False
        self.state["heard_at"] = self.state["first_audio_at"] = self.state["speech_end_at"] = None
        self.state["channel"] = ""

    def answer_tool_call(self, call, via="function"):
        """Live의 함수 호출 하나에 돌려줄 결과를 만들고, 폰에 알릴 것이 있으면 줄에 넣는다."""
        args = call.args or {}
        if call.name == "report_current_artwork":
            artwork_id = str(args.get("artwork_id") or "")
            found = self.artworks.get(artwork_id)
            if found is None:
                # unknown이거나 목록 밖의 값. 지금 작품을 지우지 않는다(잠깐 다른 곳을 비춘 경우).
                self.vlog.event("artwork_unknown", via=via)
                return {"artwork_id": UNKNOWN,
                        "instruction": "You cannot tell which painting is in view. Do not describe any "
                                       "painting. Kindly ask the visitor to point the camera at the painting."}
            self.state["artwork_id"] = artwork_id
            self.vlog.event("artwork_identified", artwork_id=artwork_id, via=via)
            self.save_resume()
            used = list(self.visit.used_comparison_ids)
            if self.state["comparison_id"]:
                used.append(self.state["comparison_id"])
            # 화면 표시 정보도 콘텐츠 목록에서 제공한다.
            self.to_browser.put_nowait(("text", {
                "type": "artwork", "artwork_id": artwork_id, "artwork_title": found["title_en"],
                "artist": found.get("artist", "")}))
            return {
                "artwork_id": artwork_id,
                "artwork": (artwork_card(found) if live_config.LIVE_FACTS == "per_question"
                            else build_artwork_context(found)),
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
            # 비교 데이터도 콘텐츠 DB에서 받은 사실이므로 이 턴은 질문으로 센다(11/23 결정).
            # 같은 턴에 lookup_facts가 이미 라벨을 적었으면 그 값을 지키고, 없을 때만 comparison을 쓴다.
            self.state["grounded"] = True
            self.state["label"] = self.state["label"] or "comparison"
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
        if call.name in ("lookup_facts", "report_question"):
            # 관람객이 무엇을 물었는지만 기록한다. 질문 원문은 어디에도 남기지 않는다.
            self.state["label"] = normalize_label(args.get("label"))
            self.state["outcome"] = normalize_outcome(args.get("outcome"))
            if call.name == "report_question":
                self.state["grounded"] = True    # per_artwork: 사실은 이미 줬고, 보고가 질문의 표시다
                return {"ok": True}
            found = self.artworks.get(self.state["artwork_id"])
            if found is None:
                # 작품이 아직 인식되지 않았다. 사실을 줄 수 없으므로 조회로 세지 않는다.
                return {"ok": False, "error": "No artwork is identified yet. Do not answer about any "
                                              "painting. Look at the camera and call report_current_artwork."}
            self.state["grounded"] = True
            return {"ok": True, "facts": build_artwork_context(found),
                    "note": "These facts are for this question only. Call lookup_facts again for the next one."}
        return {"ok": False, "error": f"unknown function {call.name}"}

