"""Live API에 음성을 넣어 받아쓰기·답변·시간을 확인한다(FE1 전환 검토용 측정 도구).

담당: FE1
같이 보는 파일: tools/compare_modes.py (BE1의 방식 비교, 텍스트 질문만 씀),
              tools/live_relay_spike.py (브라우저 ↔ 서버 ↔ Gemini 중계 시험대),
              docs/FE1_Live_검토.md (이 도구로 얻은 결과와 판단)

BE1의 compare_modes.py는 Live에 질문을 '텍스트'로 보낸다. 이 도구는 '음성'을 보낸다.
브라우저 음성 인식(static/stt.js)을 Live의 받아쓰기로 대체할 수 있는지가 FE1의 갈림길이므로,
실제 음성을 넣었을 때 무엇을 들었고 몇 초에 답이 시작되는지를 직접 재야 한다.

설치: uv sync --extra live
준비(맥에서 시험용 음성 만들기. 실제 관람객 음성을 저장하지 않기 위해 합성음을 쓴다):
    say -v Samantha -o /tmp/q.aiff "Who painted this, and why is the boy crying?"
    afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/q.aiff /tmp/q16k.wav
실행:
    PYTHONPATH=. uv run python tools/probe_live_audio.py /tmp/q16k.wav gemini-3.8-live KHD_SEODANG

음성은 메모리에서만 다루고 파일로 남기지 않는다(AGENTS.md).
입력은 16kHz·16bit·모노 PCM, 출력은 24kHz PCM이다(공식 문서 기준, 실제 mime으로 확인함).
"""
import asyncio, sys, time, wave
from google.genai import types
from server.ask import build_artwork_context
from server.content import load_artworks
from server.gemini_client import make_client
from server.prompts import ASK_INSTRUCTION

WAV, MODEL, ARTWORK = sys.argv[1], sys.argv[2], sys.argv[3]
CHUNK_MS = 100  # 폰에서 보내는 것처럼 100ms씩 쪼개 보낸다

def read_pcm(path):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, w.getparams()
        return w.readframes(w.getnframes()), w.getnframes() / 16000

async def main():
    pcm, seconds = read_pcm(WAV)
    art = load_artworks()[ARTWORK]
    client = make_client()
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=f"{ASK_INSTRUCTION}\n\n{build_artwork_context(art)}",
        input_audio_transcription=types.AudioTranscriptionConfig(),   # 관람객 말을 글로
        output_audio_transcription=types.AudioTranscriptionConfig(),  # 답변을 글로
    )
    print(f"모델 {MODEL} · 작품 {ARTWORK} · 음성 {seconds:.1f}초 ({len(pcm)} bytes)")
    t0 = time.perf_counter()
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        connect_ms = round((time.perf_counter() - t0) * 1000)
        print(f"연결 {connect_ms} ms")

        step = 16000 * 2 * CHUNK_MS // 1000
        send_started = time.perf_counter()
        for i in range(0, len(pcm), step):
            await session.send_realtime_input(
                audio=types.Blob(data=pcm[i:i + step], mime_type="audio/pcm;rate=16000"))
        await session.send_realtime_input(audio_stream_end=True)
        sent_ms = round((time.perf_counter() - send_started) * 1000)
        print(f"음성 전송 끝 {sent_ms} ms (실시간이면 {seconds*1000:.0f} ms 걸릴 분량)")

        heard, said, first_ms, audio_bytes, mimes = [], [], None, 0, set()
        async for msg in session.receive():
            c = msg.server_content
            if c is None:
                continue
            if c.input_transcription and c.input_transcription.text:
                heard.append(c.input_transcription.text)
            if c.model_turn:
                for part in c.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        if first_ms is None:
                            first_ms = round((time.perf_counter() - send_started) * 1000)
                        audio_bytes += len(part.inline_data.data)
                        if part.inline_data.mime_type:
                            mimes.add(part.inline_data.mime_type)
            if c.output_transcription and c.output_transcription.text:
                said.append(c.output_transcription.text)
            if c.turn_complete:
                break
        total_ms = round((time.perf_counter() - send_started) * 1000)

    print(f"\n첫 음성 {first_ms} ms · 전체 {total_ms} ms")
    print(f"받은 오디오 {audio_bytes} bytes · mime {sorted(mimes) or '(없음)'}")
    if audio_bytes:
        print(f"24kHz·16bit 기준 재생 길이 {audio_bytes/48000:.1f}초")
    print(f"\n[들은 질문] {''.join(heard).strip() or '(받아쓰기 없음)'}")
    print(f"[답변] {''.join(said).strip() or '(없음)'}")

asyncio.run(main())
