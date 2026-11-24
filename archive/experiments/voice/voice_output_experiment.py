"""Generate fixed synthetic listening samples; never record visitor audio.

Run with PYTHONPATH=. .venv/bin/python experiments/voice/voice_output_experiment.py OUTPUT_DIR
"""
import argparse
import asyncio
import importlib.metadata
import json
import re
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from google.genai import types
from server.gemini_client import make_client

TEXT = 'Take a moment to look closely. Kim Hong-do. Shin Yun-bok. Ssireum. Seodang. Would you like a short explanation, or more detail?'
VOICES = ['Kore', 'Puck', 'Aoede']


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = dict(created_at=datetime.now(timezone.utc).isoformat(), model='gemini-3.8-live',
                  sdk=importlib.metadata.version('google-genai'), synthetic=True,
                  text=TEXT, rows=[])
    client = make_client()
    try:
        for repeat in range(1, args.repeats+1):
            for voice in VOICES if repeat % 2 else list(reversed(VOICES)):
                row = dict(voice=voice, repeat=repeat, error=None, turn_complete=False,
                           first_audio_ms=None, audio_bytes=0, mimes=[])
                config = types.LiveConnectConfig(
                    response_modalities=['AUDIO'],
                    system_instruction='Read the user text aloud in English, exactly as written. Use a calm museum guide tone, clear pronunciation, and a moderate pace. Do not add any introduction or explanation.',
                    output_audio_transcription=types.AudioTranscriptionConfig(),
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
                audio, transcript, mimes = bytearray(), [], set()
                try:
                    started = time.perf_counter()
                    async with client.aio.live.connect(model=result['model'], config=config) as session:
                        row['connect_ms'] = round((time.perf_counter()-started)*1000)
                        started = time.perf_counter()
                        await session.send_client_content(turns=types.Content(role='user', parts=[types.Part(text=TEXT)]), turn_complete=True)

                        async def receive():
                            async for message in session.receive():
                                content = message.server_content
                                if not content:
                                    continue
                                if content.output_transcription and content.output_transcription.text:
                                    transcript.append(content.output_transcription.text)
                                if content.model_turn:
                                    for part in content.model_turn.parts or []:
                                        if part.inline_data and part.inline_data.data:
                                            if row['first_audio_ms'] is None:
                                                row['first_audio_ms'] = round((time.perf_counter()-started)*1000)
                                            audio.extend(part.inline_data.data)
                                            mimes.add(part.inline_data.mime_type)
                                if content.turn_complete:
                                    row['turn_complete'] = True
                                    return
                        await asyncio.wait_for(receive(), 45)
                        row['total_ms'] = round((time.perf_counter()-started)*1000)
                except Exception as error:
                    row['error'] = type(error).__name__
                row['audio_bytes'] = len(audio)
                row['mimes'] = sorted(mimes)
                row['audio_seconds'] = len(audio)/48000
                row['output_transcript'] = ''.join(transcript).strip()
                normalize = lambda text: re.findall(r'[a-z]+', text.lower())
                row['script_exact'] = normalize(row['output_transcript']) == normalize(TEXT)
                if repeat == 1 and audio and row['turn_complete'] and mimes == {'audio/pcm;rate=24000'}:
                    with wave.open(str(args.output_dir / f'{voice}.wav'), 'wb') as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(24000)
                        output.writeframes(audio)
                result['rows'].append(row)
                (args.output_dir/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
                print(f'{voice} repeat={repeat} audio={len(audio)} error={row["error"]}', flush=True)
    finally:
        await client.aio.aclose()


if __name__ == '__main__':
    asyncio.run(main())
