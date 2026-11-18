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

폰이 다시 붙을 때(11/18 오후, 스마트글라스·폰 화면 꺼짐 대비):
    폰 WS가 끊겨도 Gemini 재개 핸들과 지금 작품을 session_id별로 이 모듈의 저장소(resume_store)에
    남겨 둔다. 폰이 같은 session_id와 "resume": true로 다시 붙으면 그 핸들로 Gemini 대화를 잇고
    인사하지 않는다(ready.resumed=true). 핸들이 없거나 2시간이 지났거나 거부되면 새 대화로 시작하되
    처음 인사 대신 "다시 연결됐다"고 짧게 말하고, 저장된 작품의 사실을 넘겨 이어 말하게 한다
    (ready.resumed=false). 같은 session_id로 WS가 둘 붙으면 앞의 것을 닫는다.
    저장소는 서버 메모리에만 있다(서버를 다시 켜면 사라진다. 대화 내용은 Gemini 쪽에만 있다).

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
import re
import unicodedata
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
from . import visit_log

router = APIRouter()
artworks = load_artworks()
comparisons = load_comparisons()
# handsfree 함수 결과에는 검증된 비교쌍만 쓴다(live_context.comparison_block과 같은 기준).
verified_comparisons = {c["comparison_id"]: c for c in comparisons
                        if c.get("verification_status", "").strip().lower() == "verified"}

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# 아래 네 도우미로만 환경 변수를 읽는다. 값이 비었거나 이상해도 예외를 올리지 않고 경고 한 줄을
# 찍은 뒤 기본값을 쓴다. 불러오는 중에 예외가 나면 uvicorn이 통째로 죽고, 오류가 server/live.py를
# 가리켜서 서버를 처음 켜는 사람은 원인이 .env의 오타라는 것을 알 수 없다.
def _env_text(name, default):
    """`.env`에 이름만 쓰고 값을 비워 둔 줄(`LIVE_MODEL=`)도 기본값으로 떨어뜨린다."""
    return os.environ.get(name, "").strip() or default


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        print(f"[live] {name} 값이 숫자가 아니라 기본값 {default}을 쓴다")
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        print(f"[live] {name} 값이 숫자가 아니라 기본값 {default}을 쓴다")
        return default


def _env_choice(name, default, allowed):
    """대소문자는 가리지 않는다. 돌려주는 값은 allowed에 적힌 철자 그대로다."""
    value = _env_text(name, default)
    for ok in allowed:
        if value.lower() == ok.lower():
            return ok
    print(f"[live] {name}={value}는 {'/'.join(allowed)} 가운데 없다. 기본값 {default}로 간다")
    return default


# 음성 모델은 요청-응답 모델과 다르다(.env의 GEMINI_MODEL은 /api/turn·/api/ask가 쓴다).
LIVE_MODEL = _env_text("LIVE_MODEL", "gemini-3.8-live")
# 도슨트 목소리. 팀 규칙(11/13): 청취로 정하지 못하면 Kore. 두 모드가 같은 목소리를 쓴다.
LIVE_VOICE = _env_text("LIVE_VOICE", "Kore")

# handsfree 자동 음성 감지 조절점(11/18 실기기에서 "음", "네" 같은 추임새에도 답해서 더함).
#   LIVE_START_SENSITIVITY: LOW면 말의 시작을 덜 자주 잡는다(짧은 추임새를 덜 잡는다). 기본 LOW.
#   LIVE_SILENCE_MS: 이만큼 조용하면 말이 끝났다고 본다. 기본 700(공식 문서 권장 500~800).
#   LIVE_PREFIX_MS: 말로 인정하기 전에 필요한 말소리 길이. 기본 300.
# 필드 이름은 google-genai 2.34.0 types.py의 AutomaticActivityDetection·StartSensitivity로 확인.
LIVE_START_SENSITIVITY = _env_choice("LIVE_START_SENSITIVITY", "LOW", ("LOW", "HIGH"))
LIVE_SILENCE_MS = _env_int("LIVE_SILENCE_MS", 700)
LIVE_PREFIX_MS = _env_int("LIVE_PREFIX_MS", 300)

# handsfree 사진 정책(11/18 실기기에서 답 도중 목소리가 바뀌었다. 영상이 들어가면 더 잦다는 포럼 측정이 있다).
#   every: 폰이 보낸 사진을 받는 대로 넘긴다(기본).
#   on_speech: 서버가 최신 1장만 들고 있다가, 관람객 말이 시작된 신호(그 턴의 첫 받아쓰기)와 글 질문 때
#              1장만 넘긴다. Gemini 연결 직후 처음 오는 1장도 넘긴다.
FRAME_POLICY = _env_choice("LIVE_FRAME_POLICY", "every", ("every", "on_speech"))

# handsfree에서 폰이 이 시간(초) 동안 아무것도 보내지 않으면(소리·사진·글·ping) 죽은 연결로 보고 닫는다.
# 11/18 실기기: 잠금을 풀자 Safari가 페이지를 새로 불렀는데 앞 WS의 끝을 서버가 알지 못해(cloudflared 경유)
# Gemini 세션이 계속 살아 있었다. 폰은 화면이 보일 때 100ms마다 소리를, 5초마다 ping을 보낸다.
PHONE_IDLE_S = _env_float("LIVE_PHONE_IDLE_S", 30)


def env_summary_line():
    """지금 적용된 Live 설정 한 줄. API 키는 넣지 않는다."""
    return (f"[live] model={LIVE_MODEL} voice={LIVE_VOICE} frame_policy={FRAME_POLICY} "
            f"start={LIVE_START_SENSITIVITY} silence={LIVE_SILENCE_MS}ms "
            f"prefix={LIVE_PREFIX_MS}ms idle={PHONE_IDLE_S:g}s")


_config_line_printed = False


def print_live_config():
    """불러오는 시점에 찍으면 uvicorn 배너에 묻히므로 시작 이벤트에서 찍는다.

    include_router가 이 핸들러를 app 쪽으로 복사하면서 라우터에도 남겨 두어 시작 때 두 번 불린다
    (fastapi 0.162.0 · starlette 1.10.0에서 확인). 줄은 한 번만 찍는다.
    """
    global _config_line_printed
    if not _config_line_printed:
        _config_line_printed = True
        print(env_summary_line(), flush=True)


router.add_event_handler("startup", print_live_config)

# 말의 앞뒤에 넣는 무음(push 모드). 경계에 말이 바로 붙으면 첫 단어·끝 단어가 잘린다. 11/11 측정에서
# 취약 문장 5개를 조건별 5회(각 25건) 시험해 완전 일치가 10/25 → 25/25였다.
SILENCE_MS = 300
SILENCE_PCM = b"\x00\x00" * (16000 * SILENCE_MS // 1000)  # 16kHz 16bit 모노 무음

HANDLE_GIVE_UP = 3       # 연달아 이 횟수만큼 실패하면 재개 핸들을 버린다
RECONNECT_WAIT_MAX = 5   # 재연결 사이 최대 대기(초)

UNKNOWN = "unknown"

# 폰이 다시 붙을 때 이어 쓸 것. session_id → {"handle", "artwork_id", "updated"(time.time())}.
# 공식 문서(session-management): 재개 핸들은 마지막 세션 종료 뒤 2시간 유효하다. 넘은 것은 버린다.
HANDLE_TTL_S = 2 * 60 * 60
resume_store = {}
# 지금 붙어 있는 폰 WS. session_id → 앞 연결을 닫게 하는 함수. 같은 관람에 WS가 둘이면 Gemini
# 세션도 둘이 되어 서로 다른 대화가 생긴다. 그래서 새 연결이 오면 앞의 것을 닫는다.
active_connections = {}


def saved_resume(session_id):
    """저장된 재개 정보. 2시간이 지났으면 지우고 None."""
    now = time.time()
    for sid in [k for k, v in resume_store.items() if now - v["updated"] > HANDLE_TTL_S]:
        del resume_store[sid]
    return resume_store.get(session_id)

# handsfree에서 연결 직후 Live가 먼저 말하게 하는 신호. 관람객의 말이 아니므로 관람 기억에 넣지 않는다.
# handsfree에서 대화를 잇지 못하고(핸들 없음·만료·거부) 새로 붙었을 때의 신호. 관람객은 방금까지 이야기하던
# 중이므로 처음 인사를 다시 하면 어색하다. 짧게 돌아왔다고만 말하게 한다.
RECONNECT_CUE = ("[The connection to the visitor dropped for a moment and you lost the earlier conversation. "
                 "Do not greet or introduce yourself again. Say in one short sentence that you are back, "
                 "and invite the visitor to continue.]")

GREETING_CUE = ("[The visitor has just started the tour and is listening. Greet them briefly in one "
                "sentence, then ask where they are from and what kind of art they enjoy. "
                "Do not describe any painting yet.]")


@router.get("/live")
def live_test_page():
    """Live 음성 시험 페이지. 운영 화면이 아니다(관람객 화면은 FE2의 `/`).

    아이폰 Safari에서 마이크 16kHz 전송과 24kHz 재생이 되는지 확인하는 데 쓴다.
    """
    return FileResponse(STATIC_DIR / "live_test.html")


# 답변 받아쓰기에 섞여 오는 표시. 11/18 실측: 추임새에 침묵하려던 턴의 받아쓰기가 "<no speech>{pause}"나
# 폭 없는 문자(U+200B)만으로 왔다. 그대로 보내면 폰의 도슨트 말풍선에 그 글자가 뜬다.
SAID_MARKUP = re.compile(r"<no speech>|\{pause\}|[\u200b\u200c\u200d\ufeff]")


def clean_said(text):
    """받아쓰기 조각에서 말이 아닌 표시를 뺀다. 남는 말이 없으면 빈 문자열."""
    cleaned = SAID_MARKUP.sub("", text)
    return cleaned if cleaned.strip() else ""


# 답변 받아쓰기 끝에 섞여 오는 모델 속 글. 말소리에는 없고 받아쓰기 길로만 온다.
# 11/18 실측(gemini-3.8-live, handsfree 인사 턴, 포트 8055):
#   "...art you enjoy?---\n(No function call needed, per instructions to greet first.)---"
#   "...art you enjoy. =========================================="
#   "...do you usually enjoy? -=call:report_current_artwork{artwork_id:unknown…"(멘토 전달본 증상)
# 가로줄·등호가 이어진 토막과 함수 이름은 도슨트가 입으로 낼 말이 아니다(지시문도 함수 이름을
# 소리 내어 읽지 말라고 적어 둔다). 이것이 보이면 그 턴의 남은 받아쓰기는 폰에 보내지 않고
# 관람 기억에도 넣지 않는다. 서버 로그에는 왜 걸렀는지 아는 데 필요한 앞부분만 적는다.
LEAK_MARK = re.compile(r"-=|=-|[-=]{3,}|report_current_artwork|report_comparison")
# 로그에 찍는 앞부분의 길이. 걸러 낸 글은 늘 표시(LEAK_MARK)로 시작하므로 이 길이면 어떤
# 표시였는지 다 보인다. 가장 긴 표시가 report_current_artwork(22자)다.
LEAK_LOG_CHARS = 32
# 조각이 끊겨 와도 놓치지 않게, 표시의 앞부분으로 끝나는 꼬리는 다음 조각까지 들고 있는다.
LEAK_WORDS = ("-=", "=-", "---", "report_current_artwork", "report_comparison")


def leak_hold(text):
    """다음 조각과 이어 봐야 표시인지 알 수 있는 꼬리의 길이."""
    for n in range(min(len(text), max(len(w) for w in LEAK_WORDS) - 1), 0, -1):
        tail = text[-n:]
        if any(len(w) > n and w.startswith(tail) for w in LEAK_WORDS):
            return n
    return 0


def feed_said(state, chunk):
    """받아쓰기 조각을 넣고 지금 폰에 보낼 말을 돌려준다. 속 글이 시작되면 그 턴은 더 보내지 않는다."""
    if state["said_leak"]:
        state["said_leak"] += chunk
        return ""
    buf = state["said_hold"] + chunk
    found = LEAK_MARK.search(buf)
    if found:
        state["said_hold"] = ""
        state["said_leak"] = buf[found.start():]
        return clean_said(buf[:found.start()])
    hold = leak_hold(buf)
    state["said_hold"] = buf[len(buf) - hold:] if hold else ""
    return clean_said(buf[:len(buf) - hold])


def flush_said(state):
    """턴이 끝났다. 들고 있던 말을 내보내고, 걸러 낸 것이 있으면 로그에 남긴다."""
    rest = clean_said(state["said_hold"])
    state["said_hold"] = ""
    if state["said_leak"]:
        # 표시 뒤에는 도슨트가 관람객에게 한 말이 이어져 있다. 배포할 때 이 출력을 파일로
        # 넘기면 그 말이 저장되므로(AGENTS.md: 음성은 처리에만 쓰고 저장하지 않는다)
        # 표시 부분만 찍고 나머지는 길이만 적는다.
        head = state["said_leak"][:LEAK_LOG_CHARS]
        hidden = len(state["said_leak"]) - len(head)
        print(f"[live] 모델 속 글이 답변 받아쓰기에 섞여 와서 걸러 냈다: {head!r}"
              + (f" + 뒤에 {hidden}자" if hidden else ""))
        state["said_leak"] = ""
    return rest


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
        "- Never read ids or function names aloud.\n"
        "- When the visitor only makes a short backchannel or filler (for example \"mm-hmm\", \"yeah, I see\", "
        "\"uh-huh\"), talks to themselves, or talks with someone else, do not respond at all: produce no "
        "words. Never announce, explain, or describe that you are staying silent. "
        "A short \"yes\" or \"okay\" right after you asked a question is an answer to it, not a filler. "
        "Speak only when they ask you something or clearly talk to you.",
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
            # 민감도·침묵 길이·앞 여유는 환경 변수로 조절한다(위 LIVE_START_SENSITIVITY 등).
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity(f"START_SENSITIVITY_{LIVE_START_SENSITIVITY}"),
                silence_duration_ms=LIVE_SILENCE_MS,
                prefix_padding_ms=LIVE_PREFIX_MS,
            ),
            # 기본값(TURN_INCLUDES_ONLY_ACTIVITY)은 말이 없던 동안의 입력을 턴에서 뺀다. 사진은 말과
            # 상관없이 3초마다 오므로 모두 넣는다(SDK 설명: "audio activity and all video").
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO,
        ),
        session_resumption=types.SessionResumptionConfig(),
        # 음성+영상은 압축이 없으면 2분에서 끝난다. 반드시 켠다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


# ── 받아쓰기로 비교 찾기 (11/18 실측: Live가 비교를 말하면서 report_comparison을 부르지 않은 턴이 있었다) ──
ARTICLES = {"the", "a", "an"}
SHORT_TITLE_CHARS = 10   # 이보다 짧거나 한 단어인 제목은 흔한 말과 겹칠 수 있어 작가 이름도 함께 나와야 인정한다


def normalize_words(text):
    """대소문자·악센트·따옴표·문장부호·관사 차이를 없앤 ' 단어 단어 ' 꼴(앞뒤 공백은 단어 경계용)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", text).split() if w not in ARTICLES]
    return " " + " ".join(words) + " "


def title_variants(title):
    """비교쌍 제목에서 관람객에게 말할 법한 이름들을 뽑는다.

    예: "Hokusai Sketchbooks (Denshin kaishu: Hokusai manga), first volume"
        → "Hokusai Sketchbooks", "Denshin kaishu", "Hokusai manga"
        "South Wind, Clear Sky (Gaifū kaisei), also known as Red Fuji, from the series ..."
        → "South Wind, Clear Sky", "Gaifū kaisei", "Red Fuji" (연작 이름은 그 작품이 아니므로 뺀다)
    """
    variants = [title.split("(")[0]]
    for inner in re.findall(r"\(([^)]*)\)", title):
        variants += inner.split(":")
    aka = re.search(r"also known as (.+?)(?:,| from |$)", title)
    if aka:
        variants.append(aka.group(1))
    out = []
    for v in variants:
        v = re.split(r",\s*(?:first|second|third) volume|\bfrom the series\b", v)[0]
        norm = normalize_words(v)
        if norm.strip() and norm not in out:
            out.append(norm)
    return out


def artist_words(artist):
    """작가 이름에서 알아볼 단어(4자 이상, Elder 같은 말 제외). "Pieter Bruegel the Elder (…)" → pieter, bruegel."""
    name = normalize_words(artist.split("(")[0])
    return [w for w in name.split() if len(w) >= 4 and w not in {"elder", "younger"}]


def comparison_in_transcript(said, artwork_id):
    """답변 받아쓰기에 지금 작품의 검증된 비교쌍 제목이 나오면 그 comparison_id(가장 먼저 나온 것).

    다른 작품의 비교쌍은 보지 않는다. 짧은 제목은 작가 이름도 함께 나와야 한다.
    """
    text = normalize_words(said)
    found = []
    for cid, pair in verified_comparisons.items():
        if pair["artwork_id"] != artwork_id:
            continue
        for variant in title_variants(pair["foreign_title"]):
            at = text.find(variant)
            if at < 0:
                continue
            short = len(variant.strip()) < SHORT_TITLE_CHARS or len(variant.split()) < 2
            if short and not any(f" {w} " in text for w in artist_words(pair["foreign_artist"])):
                continue
            found.append((at, cid))
    return min(found)[1] if found else ""


def comparison_display(comparison_id):
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

    # 관람 기록(FE1). 기본값은 꺼짐이고, LIVE_VISIT_LOG가 team·visitor일 때만 파일을 만든다.
    # 꺼져 있으면 아무것도 하지 않는 기록기가 와서 아래 vlog.event(...) 줄은 그냥 지나간다.
    # 넣을 수 있는 칸은 server/visit_log.py의 ALLOWED에 적혀 있다 — 들은 말·한 말은 넣을 칸이 없다.
    vlog = visit_log.start(mode=mode, model=LIVE_MODEL, voice=LIVE_VOICE,
                           ui_lang=str(profile.get("language") or "en")[:16])

    # 관람 기억. 폰이 /api/session에서 받은 session_id를 보내면 그 관람에 이어 쓴다. 없거나
    # 서버를 다시 켜서 사라졌으면 새로 만들고 ready에 담아 돌려준다(폰이 요약 화면에 쓴다).
    visit = sessions.get_session(first.get("session_id") or "") or sessions.create_session()
    sid = visit.session_id

    # 다시 붙는 폰이면 저장해 둔 재개 핸들과 작품을 이어받는다.
    want_resume = first.get("resume") is True
    saved = saved_resume(sid) if want_resume else None
    if mode == "handsfree" and art is None and saved and saved.get("artwork_id") in artworks:
        art_from_resume = saved["artwork_id"]
    else:
        art_from_resume = ""

    # 같은 관람의 앞 연결을 닫는다(폰이 다시 붙었는데 앞 WS가 아직 살아 있는 경우).
    kicked = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = active_connections.get(sid)
    if previous:
        previous()
    my_kick = lambda: loop.call_soon_threadsafe(kicked.set)  # noqa: E731 (다른 이벤트 루프에서도 불린다)
    active_connections[sid] = my_kick

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
    state = {"session": None, "handle": saved["handle"] if saved else None, "turn_open": False,
             "heard": "", "said": "",
             "artwork_id": art["artwork_id"] if art else art_from_resume, "comparison_id": "",
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

    async def send_frame(session, jpeg):
        await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))

    def push_said(text):
        """걸러 낸 뒤 남은 답변 받아쓰기를 폰에 보내고 관람 기억에 쌓는다."""
        if text:
            state["said"] += text
            to_browser.put_nowait(("text", {"type": "said", "text": text}))

    async def end_opening_turn(session):
        """인사 턴이 끝났다. 그동안 들고 있던 사진 1장을 바로 넘긴다."""
        if state["opening_turn"]:
            state["opening_turn"] = False
            state["first_frame_sent"] = True   # on_speech: 이 1장이 그 연결의 첫 사진이다
            await send_held_frame(session)

    async def send_held_frame(session):
        """on_speech 정책: 들고 있던 최신 사진 1장을 넘긴다(넘긴 뒤 비운다. 같은 사진을 거듭 넣지 않는다)."""
        jpeg, state["latest_frame"] = state["latest_frame"], None
        if jpeg:
            await send_frame(session, jpeg)

    def save_resume():
        """재개 핸들·지금 작품을 저장소에 남긴다. 폰 WS가 끊겨도 다음 연결이 이어 쓴다."""
        if state["handle"] or state["artwork_id"]:
            resume_store[sid] = {"handle": state["handle"], "artwork_id": state["artwork_id"],
                                 "updated": time.time()}

    # 폰으로 보낼 것을 담아 두는 줄. Gemini를 읽는 일과 폰으로 보내는 일을 떼어 놓는다.
    # 붙여 두면 폰 전송이 느릴 때 Gemini 쪽 소켓을 읽지 못해 연결이 위험해진다(11/11에 끊겼다).
    to_browser = asyncio.Queue()

    def first_audio_ms():
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
        audio_at = state["first_audio_at"]
        base = state["speech_end_at"] or state["heard_at"]
        if not base or not audio_at:
            return -1
        gap_ms = int((audio_at - base) * 1000)
        # 받아쓰기를 기준으로 쓴 턴에서 간격이 비현실적으로 짧으면(받아쓰기가 답보다 늦게 온 것)
        # 잴 수 없는 것으로 둔다. 실측에서 함수를 거치지 않는 턴도 1.2초 아래로 내려가지 않았다.
        if state["speech_end_at"] is None and gap_ms < 300:
            return -1
        return gap_ms

    def remember_turn():
        """이번 턴을 관람 기억에 넣는다. BE1의 session.record_turn을 부르기만 한다.

        push는 comparison_id가 늘 빈 값이다(음성 답에서 어떤 비교를 썼는지 알 수 없다. 추측하지 않는다).
        handsfree는 이번 턴에 Live가 report_comparison으로 보고한 값을 넘긴다.
        """
        said = state["said"].strip()
        if not said:
            return
        if mode == "handsfree" and not state["comparison_called"] and state["artwork_id"] in artworks:
            # Live가 함수를 부르지 않고 비교를 말한 턴. 답에 지금 작품의 비교쌍 제목이 나오면 같은 처리를 한다.
            cid = comparison_in_transcript(said, state["artwork_id"])
            if cid and cid not in visit.used_comparison_ids:
                print(f"[live] 함수 없이 말한 비교를 받아쓰기에서 찾음: {cid}")
                state["comparison_id"] = cid
                to_browser.put_nowait(("text", {
                    "type": "comparison", "comparison_id": cid, "artwork_id": state["artwork_id"],
                    "source": "transcript", **comparison_display(cid)}))
                vlog.event("comparison", artwork_id=state["artwork_id"], comparison_id=cid,
                           via="transcript")
        visit.record_turn(state["heard"].strip(), SimpleNamespace(
            artwork_id=state["artwork_id"], comparison_id=state["comparison_id"], reply=said))
        # 관람 기록: 질문 한 번. 글자는 넣지 않는다(기록 모듈이 거부한다).
        # 관람객이 아무 말도 하지 않은 턴(연결 직후 인사)은 질문으로 세지 않는다.
        # label·outcome은 아직 빈 값이다 — 라벨 체계(FE3)와 no_source 판정(BE1)을 정해야 채운다.
        if state["heard"].strip():
            vlog.event("question", artwork_id=state["artwork_id"],
                       channel=state["channel"] or "voice", label="", outcome="",
                       first_audio_ms=first_audio_ms())
        state["heard"] = state["said"] = state["comparison_id"] = ""
        state["comparison_called"] = False
        state["heard_at"] = state["first_audio_at"] = state["speech_end_at"] = None
        state["channel"] = ""

    def answer_tool_call(call):
        """Live의 함수 호출 하나에 돌려줄 결과를 만들고, 폰에 알릴 것이 있으면 줄에 넣는다."""
        args = call.args or {}
        if call.name == "report_current_artwork":
            artwork_id = str(args.get("artwork_id") or "")
            found = artworks.get(artwork_id)
            if found is None:
                # unknown이거나 목록 밖의 값. 지금 작품을 지우지 않는다(잠깐 다른 곳을 비춘 경우).
                vlog.event("artwork_unknown", via="function")
                return {"artwork_id": UNKNOWN,
                        "instruction": "You cannot tell which painting is in view. Do not describe any "
                                       "painting. Kindly ask the visitor to point the camera at the painting."}
            state["artwork_id"] = artwork_id
            vlog.event("artwork_identified", artwork_id=artwork_id, via="function")
            save_resume()
            used = list(visit.used_comparison_ids) + ([state["comparison_id"]] if state["comparison_id"] else [])
            # 화면이 작품 목록을 베껴 두지 않게 보여 줄 값을 같이 보낸다(11/18). 베낀 목록은
            # 예원님이 CSV를 늘릴 때마다 어긋났다 — 하루에 두 번 났다.
            to_browser.put_nowait(("text", {
                "type": "artwork", "artwork_id": artwork_id, "artwork_title": found["title_en"],
                "artist": found.get("artist", "")}))
            return {
                "artwork_id": artwork_id,
                "artwork": build_artwork_context(found),
                "comparison_options": comparison_block(comparisons, artwork_id, profile, used),
                # comparison_options와 같은 순서. report_comparison에 넣을 값이다.
                "comparison_ids": ranked_comparison_ids(artwork_id, profile, used),
            }
        if call.name == "report_comparison":
            state["comparison_called"] = True   # 이 턴은 받아쓰기로 비교를 찾지 않는다
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
                "type": "comparison", "comparison_id": comparison_id, "artwork_id": pair["artwork_id"],
                "source": "function", **comparison_display(comparison_id)}))
            vlog.event("comparison", artwork_id=pair["artwork_id"], comparison_id=comparison_id,
                       via="function")
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
            state["last_input"] = time.monotonic()
            session = state["session"]
            data = None
            if msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
                if data.get("type") == "ping":
                    continue    # 살아 있다는 신호. 받기만 하고 Gemini로 보내지 않는다.
                if mode == "handsfree" and data.get("type") == "frame":
                    try:
                        jpeg = base64.b64decode(data.get("jpeg") or "", validate=True)
                    except (binascii.Error, ValueError):
                        continue
                    if not jpeg:
                        continue
                    data = {"type": "frame", "jpeg_bytes": jpeg}
                    if state["opening_turn"]:
                        # 인사 턴에는 사진을 넣지 않는다. 11/18 측정(포트 8055, 인사만 받는 왕복):
                        # 사진을 같이 넣으면 3/3이 인사 뒤에 모델 속 글을 흘렸고, 한 번은 글이
                        # "(No function call needed, per instructions to greet first.)"였다.
                        # 사진 없이는 1/3이었다. 인사 신호 자체가 "아직 그림 이야기는 하지 말라"고
                        # 적고 있으니, 인사가 끝난 뒤에 최신 1장을 넘긴다.
                        state["latest_frame"] = jpeg
                        continue
                    if FRAME_POLICY == "on_speech":
                        # 최신 1장만 들고 있는다. 연결 직후 첫 1장만 바로 넘긴다.
                        state["latest_frame"] = jpeg
                        if session is None or state["first_frame_sent"]:
                            continue
                        state["first_frame_sent"] = True
                        state["latest_frame"] = None
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
                    await send_frame(session, data["jpeg_bytes"])
                elif data.get("type") == "text":     # handsfree: 글로 묻기
                    text = (data.get("text") or "").strip()
                    if text:
                        if FRAME_POLICY == "on_speech":
                            await send_held_frame(session)   # 질문하는 순간의 사진
                        state["heard"] += text
                        state["channel"] = "text"
                        state["heard_at"] = time.monotonic()
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
                    save_resume()
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
            activity = getattr(m, "voice_activity", None)
            if activity is not None:
                kind = getattr(activity, "voice_activity_type", None)
                name = str(getattr(kind, "name", kind) or "")
                if "END" in name.upper():
                    state["speech_end_at"] = time.monotonic()
            if getattr(m, "usage_metadata", None) is not None:
                # 턴마다 여러 번 올 수 있어 마지막 것만 들고 있다가 턴이 끝날 때 한 번 적는다.
                # 이 숫자가 턴마다의 양인지 세션 누적인지는 아직 확인하지 않았다(실측 필요).
                state["usage"] = m.usage_metadata
            c = m.server_content
            if c is None:
                continue
            if c.interrupted:
                # 관람객이 답을 끊었다. 폰은 재생 중인 소리를 바로 멈춰야 한다.
                push_said(flush_said(state))
                await end_opening_turn(session)
                to_browser.put_nowait(("text", {"type": "interrupted"}))
                vlog.event("quality", issue="interrupted")
            if c.input_transcription and c.input_transcription.text:
                # 관람객이 말을 시작했으면 인사 턴은 끝난 것으로 본다(사진을 더 들고 있지 않는다).
                await end_opening_turn(session)
                if mode == "handsfree" and FRAME_POLICY == "on_speech" and not state["turn_frame_sent"]:
                    # 이번 턴의 첫 받아쓰기 = 관람객이 말을 시작했다. 그때의 사진 1장을 넘긴다.
                    # (state["heard"]로 판단하지 않는다: 추임새에 Live가 침묵하면 heard가 다음 턴까지 남는다)
                    state["turn_frame_sent"] = True
                    await send_held_frame(session)
                state["heard"] += c.input_transcription.text
                state["heard_at"] = time.monotonic()
                state["channel"] = state["channel"] or "voice"
                to_browser.put_nowait(("text", {"type": "heard", "text": c.input_transcription.text}))
            if c.model_turn:
                state["turn_open"] = True
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        if state["first_audio_at"] is None:
                            state["first_audio_at"] = time.monotonic()
                        to_browser.put_nowait(("bytes", part.inline_data.data))  # 24kHz PCM 그대로
            if c.output_transcription and c.output_transcription.text:
                state["turn_open"] = True
                push_said(feed_said(state, c.output_transcription.text))
            if c.turn_complete:
                state["turn_open"] = False
                state["turn_frame_sent"] = False
                push_said(flush_said(state))
                await end_opening_turn(session)
                remember_turn()
                if state["usage"] is not None:
                    # Gemini가 주는 숫자는 세션 누적이다(11/18 실측: total 2053→2522→3849→4166).
                    # 그대로 적으면 턴마다 더할 수 없으니 앞 턴과의 차이를 적는다.
                    # 그때의 작품을 같이 적는다. 없으면 어느 작품 설명이 비싼지 알 수 없다.
                    # 작품을 아직 모르는 턴(인사)은 빈 값이 된다.
                    now_usage = visit_log.usage_fields(state["usage"])
                    vlog.event("usage", artwork_id=state["artwork_id"],
                               **{k: max(0, v - state["usage_seen"].get(k, 0))
                                  for k, v in now_usage.items()})
                    state["usage_seen"] = now_usage
                    state["usage"] = None
                to_browser.put_nowait(("text", {"type": "turn_complete"}))
                if going_away:
                    return "go_away"
        # receive()가 한 턴을 다 내보내고 스스로 끝났다.
        return "go_away" if going_away else "turn"

    def leave_session(kept_conversation=True, announce=True):
        """Gemini 연결을 떠날 때 폰 쪽을 정리한다. 답변 도중이면 턴을 닫아 버튼을 풀어 준다.

        announce=False: 아직 ready를 보내기 전(처음 붙기가 실패함)이라 폰에 reconnecting을 알리지 않는다.
        """
        state["session"] = None
        state["opening_turn"] = False   # 연결이 바뀌면 사진을 더 들고 있지 않는다
        if state["turn_open"]:
            state["turn_open"] = False
            push_said(flush_said(state))
            remember_turn()  # 반쯤 받은 답도 들려준 만큼은 기록에 남긴다
            to_browser.put_nowait(("text", {"type": "turn_complete"}))
        if announce:
            to_browser.put_nowait(("text", {
                "type": "reconnecting", "kept_conversation": kept_conversation}))
            vlog.event("quality", issue="reconnect", kept_conversation=kept_conversation)

    def first_cue(resumed):
        """처음 붙었을 때 Live에 보낼 신호. 대화를 이었으면 없음."""
        if mode != "handsfree" or resumed:
            return None
        if not want_resume:
            return GREETING_CUE
        cue = RECONNECT_CUE
        known = artworks.get(state["artwork_id"])
        if known:
            # 대화는 잃었지만 어느 그림 앞이었는지는 안다. 함수 호출 전에도 그 작품으로 이어 말하게 사실을 넘긴다.
            cue += (f"\n[The visitor was looking at {state['artwork_id']}. Until the camera shows otherwise, "
                    f"talk about it using only these facts.]\n{build_artwork_context(known)}")
        return cue

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
                    state["first_frame_sent"] = False   # on_speech: 새 연결마다 첫 사진 1장은 바로 넘긴다
                    resumed = want_resume and had_handle
                    cue = first_cue(resumed) if first_time else None
                    if cue:
                        # 버튼이 없으므로 Live가 먼저 말을 건다(목소리 하나로 통일, 브라우저 음성 인사 없음).
                        # 다시 붙었지만 대화를 잃었으면 인사 대신 돌아왔다고만 말한다.
                        #
                        # state["session"]을 세우기 전에 보낸다. 세우는 순간부터 browser_to_gemini가
                        # 폰의 마이크 PCM과 사진을 send_realtime_input으로 흘리는데, google-genai
                        # 2.34.0 live.py의 send_client_content 주의문이 "같은 대화에서 둘을 섞어 쓰는
                        # 것은 권하지 않으며 예상 밖의 결과가 날 수 있다"고 적고 있다. 인사 신호가
                        # 먼저 닿도록 순서를 정해 둔다.
                        state["opening_turn"] = True
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=cue)]),
                            turn_complete=True)
                    state["session"] = session
                    to_browser.put_nowait(("text", {
                        "type": "ready" if first_time else "reconnected",
                        "model": LIVE_MODEL,
                        "mode": mode,
                        "voice": LIVE_VOICE,
                        **({"artwork_title": art["title_en"]} if art else {}),
                        "session_id": visit.session_id,
                        # 핸들 없이 새로 붙었으면 앞 대화를 잃었다는 뜻이다. 폰이 안내를 바꿀 수 있게 알린다.
                        # 폰이 resume으로 다시 붙었을 때만: 앞 대화를 이었는지
                        **({"resumed": resumed} if first_time and want_resume else {}),
                        **({} if first_time else {"kept_conversation": had_handle})}))
                    if first_time and want_resume and resumed:
                        vlog.event("quality", issue="resumed", kept_conversation=True)
                    first_time = False
                    fails = 0
                    while True:
                        if await read_one_turn(session) == "go_away":
                            break      # async with를 빠져나가 연결을 닫고 아래에서 새로 붙는다
                print(f"[live] 연결 교체(GoAway). 이 연결 수명 {time.monotonic() - opened:.0f}초")
                leave_session()
            except APIError as e:
                if active_connections.get(sid) is not my_kick:
                    # 이 관람은 이미 새 폰 연결이 이어받았다(같은 핸들로 붙으면 Gemini가 앞 세션을 닫는다).
                    # 여기서 다시 붙으면 새 연결의 대화를 빼앗으므로 그만둔다.
                    print(f"[live] 세션 종료 {e.code}: 새 연결이 이어받아 이 연결은 다시 붙지 않는다")
                    return
                # 1008 비활성, 연결 수명 초과, 핸들 거부 등.
                fails += 1
                drop_handle = had_handle and fails >= HANDLE_GIVE_UP
                print(f"[live] 세션 종료 {e.code}: {e.message}. "
                      f"다시 붙는다(핸들 {'있음' if state['handle'] else '없음'}, 연달아 실패 {fails})"
                      + (" — 핸들을 버리고 새 대화로 시작한다" if drop_handle else ""))
                if drop_handle:
                    # 핸들이 문제일 가능성이 높다(2시간 만료 등). 대화를 잃더라도 도슨트를 살린다.
                    state["handle"] = None
                leave_session(kept_conversation=not drop_handle, announce=not first_time)
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
    #
    # kicked: 같은 session_id로 새 폰 연결이 오면 켜진다 → 이 연결을 닫는다.
    tasks = [asyncio.create_task(f()) for f in (browser_to_gemini, gemini_sessions, queue_to_browser)]
    tasks.append(asyncio.create_task(kicked.wait()))

    async def phone_watchdog():
        """handsfree: 폰이 PHONE_IDLE_S초 동안 아무것도 보내지 않으면 죽은 연결로 보고 끝낸다."""
        while True:
            idle = time.monotonic() - state["last_input"]
            if idle >= PHONE_IDLE_S:
                print(f"[live] 폰이 {idle:.0f}초 동안 아무것도 보내지 않아 죽은 연결로 보고 닫는다({sid[:8]})")
                vlog.event("quality", issue="phone_idle_close")
                return
            await asyncio.sleep(min(PHONE_IDLE_S - idle, 1.0))

    phone_silent = None
    if mode == "handsfree":
        phone_silent = asyncio.create_task(phone_watchdog())
        tasks.append(phone_silent)
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # 이 관람의 지금 연결에서 바로 뺀다. 아래 정리(Gemini 연결 닫기)는 몇 초 걸릴 수 있는데,
        # 그 사이 폰이 다시 붙으면 이미 떠난 연결을 '앞 연결'로 잘못 닫으려 하게 된다.
        if active_connections.get(sid) is my_kick:
            del active_connections[sid]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                print(f"[live] 중계 종료: {t.exception()!r}"[:300])
    except WebSocketDisconnect:
        pass
    finally:
        # Gemini 세션은 위에서 작업을 취소하며 닫혔다. 핸들은 남긴다(2시간 시계는 지금부터).
        # 정리하는 몇 초 사이에 새 연결이 이어받아 더 새 핸들을 저장했을 수 있으므로, 저장소의 핸들이
        # 우리 것일 때만 시각을 갱신한다(새 핸들을 옛 핸들로 덮지 않는다).
        entry = resume_store.get(sid)
        if entry is None:
            save_resume()
        elif entry["handle"] == state["handle"]:
            entry["updated"] = time.time()
        if active_connections.get(sid) is my_kick:
            del active_connections[sid]
        # 관람 기록을 닫는다. 왜 끝났는지만 남긴다(세션 ID는 남기지 않는다).
        vlog.end(reason="phone_idle" if (phone_silent is not None and phone_silent.done()
                                         and not phone_silent.cancelled())
                 else "replaced" if kicked.is_set() else "phone_closed")
    print(f"[live] 폰 연결 끝({sid[:8]}, {mode}). 저장된 핸들 "
          f"{'있음' if (resume_store.get(sid) or {}).get('handle') else '없음'}")
    if phone_silent is not None and phone_silent.done() and not phone_silent.cancelled():
        try:
            await ws.close(code=4001, reason="no input from the phone")
        except Exception:
            pass
    if kicked.is_set():
        print(f"[live] 같은 관람({sid[:8]})의 새 연결이 와서 앞 연결을 닫는다")
        try:
            await ws.close(code=4000, reason="replaced by a newer connection")
        except Exception:
            pass
