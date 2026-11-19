"""Gemini Live 연결 설정과 handsfree 도구 선언 (담당 FE1)."""
import os

from google.genai import types

from .live_context import build_live_instruction, profile_block
from .prompts import LIVE_INSTRUCTION

UNKNOWN = "unknown"

# 잘못된 환경 변수에는 경고를 남기고 기본값으로 서버를 시작한다.
def _env_text(name, default):
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
    """대소문자 구분 없이 비교하고 `allowed`에 정의된 값을 반환한다."""
    value = _env_text(name, default)
    for ok in allowed:
        if value.lower() == ok.lower():
            return ok
    print(f"[live] {name}={value}는 {'/'.join(allowed)} 가운데 없다. 기본값 {default}로 간다")
    return default


LIVE_MODEL = _env_text("LIVE_MODEL", "gemini-3.8-live")
LIVE_VOICE = _env_text("LIVE_VOICE", "Kore")

# 짧은 추임새를 발화로 감지하는 빈도를 줄인다. Live 문서의 종료 무음 권장 범위는 500~800ms다.
# SDK 필드는 google-genai 2.34.0의 AutomaticActivityDetection·StartSensitivity 참고.
LIVE_START_SENSITIVITY = _env_choice("LIVE_START_SENSITIVITY", "LOW", ("LOW", "HIGH"))
LIVE_SILENCE_MS = _env_int("LIVE_SILENCE_MS", 700)
LIVE_PREFIX_MS = _env_int("LIVE_PREFIX_MS", 300)

# handsfree 프레임 전송 시점
# - every는 모든 프레임을 전송한다.
# - on_speech는 연결 직후 첫 프레임과 음성·텍스트 질문 시작 시 최신 프레임을 전송한다.
FRAME_POLICY = _env_choice("LIVE_FRAME_POLICY", "every", ("every", "on_speech"))

# Safari가 다시 로드할 때도 소켓 종료가 누락될 수 있어 handsfree 무응답 연결을 닫는다.
PHONE_IDLE_S = _env_float("LIVE_PHONE_IDLE_S", 30)


def env_summary_line():
    """API 키를 제외한 Live 설정을 시작 로그에 표시한다."""
    return (f"[live] model={LIVE_MODEL} voice={LIVE_VOICE} frame_policy={FRAME_POLICY} "
            f"start={LIVE_START_SENSITIVITY} silence={LIVE_SILENCE_MS}ms "
            f"prefix={LIVE_PREFIX_MS}ms idle={PHONE_IDLE_S:g}s")


_config_line_printed = False


def print_live_config():
    """서버 시작 시 Live 설정을 한 번 출력한다."""
    global _config_line_printed
    if not _config_line_printed:
        _config_line_printed = True
        print(env_summary_line(), flush=True)


# 아래 두 신호는 서버에서 생성하므로 관람객 발화 이력에서 제외한다.
RECONNECT_CUE = ("[The connection to the visitor dropped for a moment and you lost the earlier conversation. "
                 "Do not greet or introduce yourself again. Say in one short sentence that you are back, "
                 "and invite the visitor to continue.]")

GREETING_CUE = ("[The visitor has just started the tour and is listening. Greet them briefly in one "
                "sentence, then ask where they are from and what kind of art they enjoy. "
                "Do not describe any painting yet.]")


def speech_config():
    """두 모드의 공통 음성 설정 (google-genai 2.34.0의 SpeechConfig 참고)."""
    return types.SpeechConfig(voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)))


def live_config(art, profile, used_ids, comparisons):
    """버튼으로 발화 범위를 지정하는 push 모드 연결 설정."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config(),
        system_instruction=build_live_instruction(art, comparisons, profile, used_ids),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # 버튼을 누른 동안에만 음성을 보내므로 자동 감지를 끈다.
        # Live API의 수동 감지 모드는 activityStart·activityEnd로 경계를 알리고 audioStreamEnd는 생략한다.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        ),
        session_resumption=types.SessionResumptionConfig(),
        # 음성 전용 세션의 15분 제한을 피하도록 문서 예시의 기본 압축 설정을 사용한다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


def handsfree_tools(artworks, verified_comparisons):
    """작품·비교 보고 도구를 선언하고 ID를 카탈로그의 값으로 제한한다."""
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
    """공통 지시문과 프로필에 전시작 목록과 도구 사용 규칙을 추가한다.

    관람 중 작품이 바뀔 때마다 도구 응답으로 작품 근거와 비교 후보를 제공한다.
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
    """음성 감지와 작품 보고 도구를 사용하는 handsfree 모드 연결 설정."""
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config(),
        system_instruction=handsfree_instruction(profile, artworks),
        tools=handsfree_tools(artworks, verified_comparisons),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            # 무음까지 연속 전송하므로 Gemini가 발화의 끝을 감지할 수 있다.
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity(f"START_SENSITIVITY_{LIVE_START_SENSITIVITY}"),
                silence_duration_ms=LIVE_SILENCE_MS,
                prefix_padding_ms=LIVE_PREFIX_MS,
            ),
            # 발화 사이에 들어온 카메라 프레임도 턴에 포함한다.
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO,
        ),
        session_resumption=types.SessionResumptionConfig(),
        # 음성·영상 세션의 2분 제한을 피하도록 압축을 사용한다.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


