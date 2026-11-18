"""Live 환경 변수와 Gemini 연결 설정. 담당: FE1.

작품·비교쌍은 호출자가 넘긴다. 프롬프트의 공통 규칙은 BE1의 live_context를 사용한다.
"""
import os

from google.genai import types

from .live_context import build_live_instruction, profile_block
from .prompts import LIVE_INSTRUCTION

UNKNOWN = "unknown"

# 아래 네 도우미로만 환경 변수를 읽는다. 값이 비었거나 이상해도 예외를 올리지 않고 경고 한 줄을
# 찍은 뒤 기본값을 쓴다. 불러오는 중에 예외가 나면 uvicorn이 통째로 죽고, 오류가 server/live_config.py를
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


# handsfree에서 연결 직후 Live가 먼저 말하게 하는 신호. 관람객의 말이 아니므로 관람 기억에 넣지 않는다.
# handsfree에서 대화를 잇지 못하고(핸들 없음·만료·거부) 새로 붙었을 때의 신호. 관람객은 방금까지 이야기하던
# 중이므로 처음 인사를 다시 하면 어색하다. 짧게 돌아왔다고만 말하게 한다.
RECONNECT_CUE = ("[The connection to the visitor dropped for a moment and you lost the earlier conversation. "
                 "Do not greet or introduce yourself again. Say in one short sentence that you are back, "
                 "and invite the visitor to continue.]")

GREETING_CUE = ("[The visitor has just started the tour and is listening. Greet them briefly in one "
                "sentence, then ask where they are from and what kind of art they enjoy. "
                "Do not describe any painting yet.]")


def speech_config():
    """목소리 설정. 필드 이름은 google-genai 2.34.0 types.py(SpeechConfig·VoiceConfig·PrebuiltVoiceConfig)로 확인."""
    return types.SpeechConfig(voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)))


def live_config(art, profile, used_ids, comparisons):
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
def handsfree_tools(artworks, verified_comparisons):
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


def handsfree_instruction(profile, artworks):
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


def handsfree_config(profile, artworks, verified_comparisons):
    """handsfree 모드 Live 연결 설정. 세션 수명 설정(재개·압축)은 push와 같다."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config(),
        system_instruction=handsfree_instruction(profile, artworks),
        tools=handsfree_tools(artworks, verified_comparisons),
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


