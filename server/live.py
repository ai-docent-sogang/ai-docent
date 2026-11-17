"""폰 ↔ 우리 서버 ↔ Gemini Live 음성 중계. 운영 서버의 `/ws/live`에 붙는다.

담당: FE1
같이 보는 파일: live_context.py (지시문 조각, BE1), prompts.py (LIVE_INSTRUCTION, BE1),
              session.py (관람 기억, BE1), ask.py (build_artwork_context, BE1),
              content.py (작품·비교쌍, BE2), docs/api.md (WS 형식),
              tools/fake_browser_live.py (실제 Gemini로 하는 확인),
              tools/live_frame_recognition.py (Live + 함수 호출 + 사진을 처음 돌려 본 도구),
              tests/test_live_session_lifetime.py (가짜 Gemini로 하는 시험)

왜 중계가 필요한가:
    AGENTS.md는 클라이언트 코드에 API 키를 넣지 못하게 한다. 그래서 폰 브라우저가 Gemini Live에
    직접 붙을 수 없고, 우리 서버가 가운데서 음성을 넘겨주어야 한다.

두 가지 모드(첫 메시지의 "mode"로 고른다, 11/18 T1·T2 계약):
    push(기본, `/live` 시험 페이지):
        버튼을 누르는 동안만 소리를 받는다. 자동 음성 감지를 끄고 speech_start·speech_end로
        말의 경계를 알린다. 연결할 때 받은 작품 한 점으로 고정하고 지시문은 BE1의
        build_live_instruction을 그대로 쓴다. 11/17 동작 그대로다.
    handsfree(AIVY 화면, 11/18 추가):
        버튼 없이 사람과 말하듯 대화한다.
        - 폰이 마이크 PCM을 쉬지 않고 보내고, Gemini의 자동 음성 감지가 말의 시작·끝을 판단한다.
          관람객이 답을 끊으면 Gemini가 interrupted를 주고, 우리는 폰에 그대로 알린다(재생 멈춤).
        - 폰이 3초마다 카메라 사진을 보낸다. 작품은 연결할 때 정하지 않고 Live가 사진으로 알아본다.
        - Live가 함수 두 개를 부른다. report_current_artwork(어느 작품인지) → 우리는 그 작품의
          확인된 사실과 비교 후보를 함수 결과로 돌려준다. report_comparison(어느 비교를 꺼내는지)
          → 우리는 그 비교쌍의 내용을 돌려주고 관람 기억에 남긴다. 그래서 push 모드에서 빈 값이던
          comparison_id가 handsfree에서는 채워진다.
        - 연결되면 Live가 먼저 짧게 인사하고 어디서 왔는지, 어떤 미술을 좋아하는지 묻는다.

아직 없는 것:
    - **프로필 변경.** 연결할 때 한 번만 넣는다(11/17 BE1 결정). handsfree에서 관람객이 말로
      출신을 알려 줘도 비교 후보의 순서는 첫 메시지의 profile로 정한다(모델은 후보 둘을 다 본다).
    - 여러 관람객 동시 접속과 인증(11/13 팀장 결정, 12/1 범위).
    - **에코 처리.** handsfree는 마이크를 계속 열어 두므로 스피커 소리를 마이크가 다시 들으면
      자기 말에 끼어들 수 있다. 서버에서는 막지 않는다(이어폰 또는 브라우저 echoCancellation 전제).
    - 10분을 넘는 실제 관람 길이의 실기기 확인. 아래 재연결은 가짜 Gemini 시험까지만 확인했다.

세션 수명(공식 문서 확인, 2026-11-14 · aistudio.google.com/docs/live-api/session-management):
    - 압축이 없으면 음성 전용 세션은 15분, 음성+영상은 2분에서 끝난다. contextWindowCompression을
      켜면 "무제한"으로 늘어난다고 적혀 있다. 그래서 켜 둔다. handsfree는 사진이 섞이므로 꼭 필요하다.
    - 연결 하나의 수명은 그와 별개로 "약 10분"이고, 연결이 끝나면 세션도 끝난다. 그래서 세션을
      여러 연결에 걸쳐 잇는 sessionResumption이 필요하다.
    - 연결이 곧 닫히기 전에 GoAway가 오고 남은 시간(timeLeft)이 함께 온다. 문서는 미리 오는
      시간을 숫자로 밝히지 않는다. 그래서 '몇 초 전에 온다'고 가정하지 않고 받는 즉시 옮긴다.
    - 재개 핸들은 "마지막 세션 종료 뒤 2시간" 유효하다. 거듭 실패하면 핸들을 버리고 새 대화로
      다시 시작한다(대화 내용은 잃는다).
"""

import asyncio
import base64
import binascii
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.genai import types
from google.genai.errors import APIError

from . import session as sessions
from .ask import build_artwork_context
from .content import load_artworks, load_comparisons, rank_comparisons
from .gemini_client import make_client
from .live_context import (MAX_COMPARISON_OPTIONS, REGION_TAGS, build_live_instruction,
                           comparison_block, profile_block)
from .prompts import LIVE_INSTRUCTION

router = APIRouter()
artworks = load_artworks()
comparisons = load_comparisons()
# handsfree 함수 결과에는 검증된 비교쌍만 쓴다(live_context.comparison_block과 같은 기준).
verified_comparisons = {c["comparison_id"]: c for c in comparisons
                        if c.get("verification_status", "").strip().lower() == "verified"}

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# 음성 모델은 요청-응답 모델과 다르다(.env의 GEMINI_MODEL은 /api/turn·/api/ask가 쓴다).
LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")
# 도슨트 목소리. 팀 규칙(11/13): 청취로 정하지 못하면 Kore. 두 모드가 같은 목소리를 쓴다.
LIVE_VOICE = os.environ.get("LIVE_VOICE", "").strip() or "Kore"

# 말의 앞뒤에 넣는 무음(push 모드). 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘린다. 11/11 측정에서
# 취약 문장 5개를 조건별 5회(각 25건) 시험해 완전 일치가 10/25 → 25/25였다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음

HANDLE_GIVE_UP = 3       # 연달아 이 횟수만큼 실패하면 재개 핸들을 버린다
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)

UNKNOWN = "unknown"

# handsfree에서 연결 직후 Live가 먼저 말하게 하는 신호. 관람객의 말이 아니므로 관람 기억에 넣지 않는다.
GREETING_CUE = ("[The visitor has just started the tour and is listening. Greet them briefly in one "
                "sentence, then ask where they are from and what kind of art they enjoy. "
                "Do not describe any painting yet.]")


@router.get("/live")
def live_test_page():
    """Live 음성 시험 페이지. 운영 화면이 아니다(관람객 화면은 FE2의 `/`).

    아이폰 Safari에서 마이크 16kHz 전송과 24kHz 재생이 되는지 확인하는 데 쓴다.
    """
    return FileResponse(STATIC_DIR / "live_test.html")


async def send_silence(session):
    await session.send_realtime_input(
        audio=types.Blob(data=SILENCE_PCM, mime_type="audio/pcm;rate=16000"))


def speech_config():
    """목소리 설정. 필드 이름은 google-genai 2.34.0 types.py(SpeechConfig·VoiceConfig·PrebuiltVoiceConfig)로 확인."""
    return types.SpeechConfig(voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)))


def live_config(art, profile, used_ids):
    """push 모드 Live 연결 설정. 지시문은 BE1의 build_live_instruction이 만든다."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config(),
        system_instruction=build_live_instruction(art, comparisons, profile, used_ids),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # 자동 음성 감지(VAD)를 끄고 말의 시작·끝을 우리가 알려 준다.
        #
        # 왜(11/11 아이폰 시험에서 두 번째 질문부터 답이 오지 않았다):
        #   기본값은 모델이 '끊기지 않는' 음성 흐름을 들으면서 침묵으로 말의 끝을 판단한다. 그런데
        #   우리 화면은 버튼을 누르는 동안만 소리를 보내므로 침묵 자체가 전달되지 않는다. 공식 문서는
        #   이런 누르고 말하기 방식에는 자동 감지를 끄고 activityStart·activityEnd로 경계를 알려
        #   주라고 안내한다(그 모드에서는 audioStreamEnd를 보내지 않는다).
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        ),
        # 끊겼을 때 대화 내용을 유지한 채 다시 붙기 위한 핸들을 받아 둔다.
        session_resumption=types.SessionResumptionConfig(),
        # 음성 전용 세션의 15분 제한을 없앤다. 값을 비워 두는 이유: 공식 문서 예시가 기본값만 쓰고
        # 트리거 토큰 수에 권장값을 주지 않는다. 우리 측정값도 없으므로 숫자를 지어내지 않는다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


# ── handsfree: 지시문과 함수 ───────────────────────────────────────────────
def handsfree_tools():
    """Live가 부를 함수 두 개. 값은 enum으로 묶어 목록 밖의 ID를 지어내지 못하게 한다."""
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="report_current_artwork",
            description=("Report which exhibition artwork the visitor's camera currently shows. "
                         "Returns the verified facts and comparison options for that artwork."),
            parameters=types.Schema(type=types.Type.OBJECT, required=["artwork_id"], properties={
                "artwork_id": types.Schema(
                    type=types.Type.STRING, enum=sorted(artworks) + [UNKNOWN],
                    description='One id from the EXHIBITION list, or "unknown" if you cannot tell.'),
            })),
        types.FunctionDeclaration(
            name="report_comparison",
            description=("Report the foreign painting you are about to compare with the current artwork. "
                         "Only ids returned by report_current_artwork for the current artwork are valid."),
            parameters=types.Schema(type=types.Type.OBJECT, required=["comparison_id"], properties={
                "comparison_id": types.Schema(
                    type=types.Type.STRING, enum=sorted(verified_comparisons),
                    description="A comparison_id from the current artwork's comparison options."),
            })),
    ])]


def handsfree_instruction(profile):
    """BE1의 규칙(LIVE_INSTRUCTION)·프로필 조각에 11점 후보와 함수 사용 규칙을 덧붙인다.

    작품 사실과 비교 후보는 지시문에 넣지 않고 함수 결과로 준다. 작품이 대화 중에 바뀌기 때문이다.
    """
    exhibition = "\n".join(f"- {art_id}: {art['title_en']}" for art_id, art in artworks.items())
    return "\n\n".join([
        LIVE_INSTRUCTION,
        profile_block(profile),
        "EXHIBITION (the only artworks in this gallery):\n" + exhibition,
        "HOW THIS CONVERSATION WORKS:\n"
        "- You receive the visitor's camera images every few seconds and hear them continuously. "
        "There is no button: speak naturally, and stop if the visitor starts talking.\n"
        "- At the start, greet once briefly and ask where the visitor is from and what kind of art "
        "they enjoy. Do not describe a painting before you have looked at the camera.\n"
        "- Before you talk about a painting, look at the latest camera image and call "
        "report_current_artwork with its id. Call it again whenever the painting in view changes. "
        "The function result contains the ARTWORK facts and COMPARISON OPTIONS; answer only from "
        "that result. The EXHIBITION list gives titles only, not facts.\n"
        '- If you are not sure which painting is in view, call report_current_artwork with "unknown" '
        "and kindly ask the visitor to point the camera at the painting. Never guess between two works.\n"
        "- Before you start a comparison with a foreign painting, call report_comparison with its "
        "comparison_id from the latest COMPARISON OPTIONS. Do not compare with anything else.\n"
        "- Never read ids or function names aloud.",
    ])


def handsfree_config(profile):
    """handsfree 모드 Live 연결 설정. 세션 수명 설정(재개·압축)은 push와 같다."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config(),
        system_instruction=handsfree_instruction(profile),
        tools=handsfree_tools(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            # 자동 음성 감지를 켠다. 폰이 침묵까지 계속 보내므로 Gemini가 말의 끝을 판단할 수 있다.
            # 민감도·침묵 길이는 기본값이다. 측정값 없이 숫자를 정하지 않는다.
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=False),
            # 기본값(TURN_INCLUDES_ONLY_ACTIVITY)은 말이 없던 동안의 입력을 턴에서 뺀다. 사진은 말과
            # 상관없이 3초마다 오므로 모두 넣는다(SDK 설명: "audio activity and all video").
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO,
        ),
        session_resumption=types.SessionResumptionConfig(),
        # 음성+영상은 압축이 없으면 2분에서 끝난다. 반드시 켠다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


def ranked_comparison_ids(artwork_id, profile, used_ids):
    """comparison_block이 적는 후보와 같은 순서의 comparison_id 목록.

    comparison_block(BE1)의 글에는 ID가 없어서 모델이 report_comparison에 넣을 값을 모른다.
    BE1 파일을 고치지 않으려고 같은 정렬(rank_comparisons + REGION_TAGS + 최대 개수)을 여기서 다시 부른다.
    live_context.comparison_block의 정렬을 바꾸면 여기도 함께 고친다.
    """
    country = (profile.get("country") or "").strip().lower()
    ranking_profile = {"country": country, "familiar_art": REGION_TAGS.get(country, [])}
    ranked = rank_comparisons(list(verified_comparisons.values()), artwork_id, ranking_profile,
                              set(used_ids))[:MAX_COMPARISON_OPTIONS]
    return [c["comparison_id"] for c in ranked]


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    await ws.accept()

    # 첫 메시지: 모드, 관람객 프로필, 이어 쓸 관람 세션. push 모드는 작품도 받는다.
    # profile과 session_id는 없어도 된다(시험 페이지는 artwork_id만 보낸다).
    first = json.loads(await ws.receive_text())
    mode = "handsfree" if first.get("mode") == "handsfree" else "push"
    art = artworks.get(first.get("artwork_id"))
    if art is None and mode == "push":
        await ws.send_text(json.dumps({"type": "error", "message": "unknown artwork"}))
        await ws.close()
        return
    profile = first.get("profile") or {}

    # 관람 기억. 폰이 /api/session에서 받은 session_id를 보내면 그 관람에 이어 쓴다. 없거나
    # 서버를 다시 켜서 사라졌으면 새로 만들고 ready에 담아 돌려준다(폰이 요약 화면에 쓴다).
    visit = sessions.get_session(first.get("session_id") or "") or sessions.create_session()

    if mode == "push":
        config = live_config(art, profile, tuple(visit.used_comparison_ids))
    else:
        config = handsfree_config(profile)
    client = make_client()

    # 지금 연결된 Live 세션과 재개 핸들. 재연결하면 session만 바뀌고 폰과의 연결은 그대로 둔다.
    #   turn_open: 답변을 내보내는 중인지. 답변 도중에 연결이 옮겨 가면 폰은 turn_complete를
    #              받지 못해 버튼이 잠긴 채로 남는다. 그래서 옮기기 전에 턴을 닫아 준다.
    #   heard/said: 이번 턴의 질문과 답을 모아 둔다. 턴이 끝나면 관람 기억에 넣는다.
    #   artwork_id: 지금 보는 작품. push는 연결할 때 고정, handsfree는 report_current_artwork로 바뀐다.
    #   comparison_id: 이번 턴에 report_comparison으로 보고된 비교(handsfree만). 기록하면 비운다.
    state = {"session": None, "handle": None, "turn_open": False, "heard": "", "said": "",
             "artwork_id": art["artwork_id"] if art else "", "comparison_id": ""}

    # 폰으로 보낼 것을 담아 두는 줄. Gemini를 읽는 일과 폰으로 보내는 일을 떼어 놓는다.
    # 붙여 두면 폰 전송이 느릴 때 Gemini 쪽 소켓을 읽지 못해 연결이 위험해진다(11/11에 끊겼다).
    to_browser = asyncio.Queue()

    def remember_turn():
        """이번 턴을 관람 기억에 넣는다. BE1의 session.record_turn을 부르기만 한다.

        push는 comparison_id가 늘 빈 값이다(음성 답에서 어떤 비교를 썼는지 알 수 없다. 추측하지 않는다).
        handsfree는 이번 턴에 Live가 report_comparison으로 보고한 값을 넘긴다.
        """
        said = state["said"].strip()
        if not said:
            return
        visit.record_turn(state["heard"].strip(), SimpleNamespace(
            artwork_id=state["artwork_id"], comparison_id=state["comparison_id"], reply=said))
        state["heard"] = state["said"] = state["comparison_id"] = ""

    def answer_tool_call(call):
        """Live의 함수 호출 하나에 돌려줄 결과를 만들고, 폰에 알릴 것이 있으면 줄에 넣는다."""
        args = call.args or {}
        if call.name == "report_current_artwork":
            artwork_id = str(args.get("artwork_id") or "")
            found = artworks.get(artwork_id)
            if found is None:
                # unknown이거나 목록 밖의 값. 지금 작품을 지우지 않는다(잠깐 다른 곳을 비춘 경우).
                return {"artwork_id": UNKNOWN,
                        "instruction": "You cannot tell which painting is in view. Do not describe any "
                                       "painting. Kindly ask the visitor to point the camera at the painting."}
            state["artwork_id"] = artwork_id
            used = list(visit.used_comparison_ids) + ([state["comparison_id"]] if state["comparison_id"] else [])
            to_browser.put_nowait(("text", {
                "type": "artwork", "artwork_id": artwork_id, "artwork_title": found["title_en"]}))
            return {
                "artwork_id": artwork_id,
                "artwork": build_artwork_context(found),
                "comparison_options": comparison_block(comparisons, artwork_id, profile, used),
                # comparison_options와 같은 순서. report_comparison에 넣을 값이다.
                "comparison_ids": ranked_comparison_ids(artwork_id, profile, used),
            }
        if call.name == "report_comparison":
            comparison_id = str(args.get("comparison_id") or "")
            pair = verified_comparisons.get(comparison_id)
            if pair is None or pair["artwork_id"] != state["artwork_id"]:
                valid = [cid for cid, c in verified_comparisons.items() if c["artwork_id"] == state["artwork_id"]]
                return {"ok": False,
                        "error": f"{comparison_id} is not a verified comparison for the current artwork "
                                 f"({state['artwork_id'] or 'none reported yet'}). Valid ids: {valid}. "
                                 "Do not make this comparison."}
            state["comparison_id"] = comparison_id
            to_browser.put_nowait(("text", {
                "type": "comparison", "comparison_id": comparison_id, "artwork_id": pair["artwork_id"]}))
            return {"ok": True, "comparison_id": comparison_id,
                    "foreign_painting": f"{pair['foreign_title']} by {pair['foreign_artist']} "
                                        f"({pair['foreign_date']}, {pair['foreign_collection']})",
                    "angle": pair["angle"], "similarities": pair["similarities"],
                    "differences": pair["differences"]}
        return {"ok": False, "error": f"unknown function {call.name}"}

    async def browser_to_gemini():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            session = state["session"]
            data = None
            if msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
            if session is None:
                # 재연결 중. 이 조각은 버린다. push는 버튼 신호마다 다시 눌러 달라고 알린다.
                # handsfree는 사진이 3초마다 오므로 글 질문에만 알린다(소리·사진은 조용히 버린다).
                if data is not None and (mode == "push" or data.get("type") == "text"):
                    to_browser.put_nowait(("text", {"type": "reconnecting"}))
                continue
            try:
                if msg.get("bytes") is not None:           # 폰 마이크 PCM 16kHz
                    await session.send_realtime_input(
                        audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                elif data is None:
                    continue
                elif mode == "push":
                    kind = data.get("type")
                    if kind == "speech_start":   # 버튼을 누른 순간
                        await session.send_realtime_input(activity_start=types.ActivityStart())
                        await send_silence(session)  # 첫 단어가 잘리지 않게 여유를 준다
                    elif kind == "speech_end":   # 버튼에서 손을 뗀 순간 → 여기서 답을 만들기 시작한다
                        await send_silence(session)  # 끝 단어가 잘리지 않게
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
                elif data.get("type") == "frame":    # handsfree: 카메라 사진(저장하지 않는다)
                    try:
                        jpeg = base64.b64decode(data.get("jpeg") or "", validate=True)
                    except (binascii.Error, ValueError):
                        continue
                    if jpeg:
                        await session.send_realtime_input(
                            video=types.Blob(data=jpeg, mime_type="image/jpeg"))
                elif data.get("type") == "text":     # handsfree: 글로 묻기
                    text = (data.get("text") or "").strip()
                    if text:
                        state["heard"] += text
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=text)]),
                            turn_complete=True)
            except Exception as e:
                # 세션이 막 끊긴 경우. 바깥 루프가 다시 붙을 때까지 흘려보낸다.
                print(f"[live] 보내기 실패(재연결 대기): {e!r}"[:200])
                state["session"] = None

    async def read_one_turn(session):
        """한 턴을 읽는다. 돌려주는 값은 왜 끝났는지다: "turn"(답변 끝) 또는 "go_away"(연결 교체).

        GoAway를 받은 뒤에도 답변이 나오는 중이면 끝까지 읽고 나서 옮긴다. 남은 시간을 문서가
        숫자로 밝히지 않으므로 '아직 여유가 있다'고 믿고 기다리지는 않는다.
        """
        going_away = False
        async for m in session.receive():
            if m.session_resumption_update and m.session_resumption_update.new_handle:
                # resumable이 꺼진 업데이트는 그 시점으로 되돌릴 수 없다는 뜻이므로 받지 않는다.
                if m.session_resumption_update.resumable is not False:
                    state["handle"] = m.session_resumption_update.new_handle
            if m.go_away:
                print(f"[live] GoAway: 남은 시간 {m.go_away.time_left}"
                      f"{' (답변 중 — 턴을 끝내고 옮긴다)' if state['turn_open'] else ''}")
                going_away = True
                if not state["turn_open"]:
                    return "go_away"
            if m.tool_call:
                # 모델은 함수 결과를 받을 때까지 기다린다. 응답은 우리가 직접 보내야 한다.
                responses = []
                for call in m.tool_call.function_calls or []:
                    result = answer_tool_call(call)
                    print(f"[live] 함수 {call.name}({json.dumps(call.args or {}, ensure_ascii=False)})"
                          f" → {result.get('artwork_id') or result.get('comparison_id') or result.get('error', '')}"[:200])
                    responses.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
                if responses:
                    await session.send_tool_response(function_responses=responses)
            c = m.server_content
            if c is None:
                continue
            if c.interrupted:
                # 관람객이 답을 끊었다. 폰은 재생 중인 소리를 바로 멈춰야 한다.
                to_browser.put_nowait(("text", {"type": "interrupted"}))
            if c.input_transcription and c.input_transcription.text:
                state["heard"] += c.input_transcription.text
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                state["turn_open"] = True
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                state["turn_open"] = True
                state["said"] += c.output_transcription.text
                to_browser.put_nowait(("text", {"type": "said", "text": c.output_transcription.text}))
            if c.turn_complete:
                state["turn_open"] = False
                remember_turn()
                to_browser.put_nowait(("text", {"type": "turn_complete"}))
                if going_away:
                    return "go_away"
        # receive()가 한 턴을 다 내보내고 스스로 끝났다.
        return "go_away" if going_away else "turn"

    def leave_session(kept_conversation=True):
        """Gemini 연결을 떠날 때 폰 쪽을 정리한다. 답변 도중이면 턴을 닫아 버튼을 풀어 준다."""
        state["session"] = None
        if state["turn_open"]:
            state["turn_open"] = False
            remember_turn()  # 반쯤 받은 답도 들려준 만큼은 기록에 남긴다
            to_browser.put_nowait(("text", {"type": "turn_complete"}))
        to_browser.put_nowait(("text", {
            "type": "reconnecting", "kept_conversation": kept_conversation}))

    async def gemini_sessions():
        """Live 세션을 열고, 끊기거나 연결 수명이 다하면 핸들로 다시 붙는다. 폰 연결은 끊지 않는다.

        session.receive()는 한 턴이 끝나면 스스로 끝나므로 안쪽에서 다시 부른다. 한 번만 돌리면
        두 번째 질문의 답이 오지 않고, 아무도 Gemini 소켓을 읽지 않아 연결이 끊긴다(11/11에 겪음).

        연결을 바꾸는 경우는 셋이다.
            1) GoAway 예고(연결 약 10분 수명) → 우리가 먼저 옮긴다.
            2) 질문 사이 2분 비활성으로 Gemini가 닫음(1008) → 다시 붙는다.
            3) 핸들이 거부됨(종료 뒤 2시간 지남 등) → 거듭 실패하면 핸들을 버리고 새로 시작한다.
        """
        first_time = True
        fails = 0           # 연달아 실패한 횟수. 재연결이 빈 바퀴를 돌지 않게 쉬는 시간을 늘린다.
        while True:
            had_handle = state["handle"] is not None
            config.session_resumption = types.SessionResumptionConfig(handle=state["handle"])
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    opened = time.monotonic()
                    state["session"] = session
                    to_browser.put_nowait(("text", {
                        "type": "ready" if first_time else "reconnected",
                        "model": LIVE_MODEL,
                        "mode": mode,
                        "voice": LIVE_VOICE,
                        **({"artwork_title": art["title_en"]} if art else {}),
                        "session_id": visit.session_id,
                        # 핸들 없이 새로 붙었으면 앞 대화를 잃었다는 뜻이다. 폰이 안내를 바꿀 수 있게 알린다.
                        **({} if first_time else {"kept_conversation": had_handle})}))
                    if first_time and mode == "handsfree":
                        # 버튼이 없으므로 Live가 먼저 말을 건다(목소리 하나로 통일, 브라우저 음성 인사 없음).
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=GREETING_CUE)]),
                            turn_complete=True)
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[live] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                # 1008 비활성, 연결 수명 초과, 핸들 거부 등.
                fails += 1
                drop_handle = had_handle and fails >= HANDLE_GIVE_UP
                print(f"[live] 세션 종료 {e.code}: {e.message}. "
                      f"다시 붙는다(핸들 {'있음' if state['handle'] else '없음'}, 연달아 실패 {fails})"
                      + (" — 핸들을 버리고 새 대화로 시작한다" if drop_handle else ""))
                if drop_handle:
                    # 핸들이 문제일 가능성이 높다(2시간 만료 등). 대화를 잃더라도 도슨트를 살린다.
                    state["handle"] = None
                leave_session(kept_conversation=not drop_handle)
                await asyncio.sleep(min(0.5 * 2 ** (fails - 1), RECONNECT_WAIT_MAX))

    async def queue_to_browser():
        """줄에 쌓인 것을 폰으로 보낸다. 느려도 Gemini 읽기를 막지 않는다."""
        while True:
            kind, payload = await to_browser.get()
            if kind == "bytes":
                await ws.send_bytes(payload)
            else:
                await ws.send_text(json.dumps(payload))

    # 셋 중 하나가 끝나면(폰이 떠났거나 오류) 나머지를 끊는다.
    #
    # 왜 gather가 아닌가: gather는 폰 쪽 루프가 끝나도 나머지를 기다린다. 그러면 관람객이 창을
    # 닫은 뒤에도 Gemini 세션이 자기 수명까지 살아 있고 우리는 그동안 재연결을 계속한다.
    tasks = [asyncio.create_task(f()) for f in (browser_to_gemini, gemini_sessions, queue_to_browser)]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                print(f"[live] 중계 종료: {t.exception()!r}"[:300])
    except WebSocketDisconnect:
        pass
