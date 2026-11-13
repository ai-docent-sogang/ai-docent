"""Synthetic speech only: alternate padding settings with real-time PCM pacing.

Run: PYTHONPATH=. .venv/bin/python experiments/voice/voice_boundary_experiment.py INPUT_DIR OUTPUT.json
No microphone recording or generated response audio is retained.
"""
import argparse
import asyncio
import importlib.metadata
import json
import platform
import re
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from google.genai import types
from server.gemini_client import make_client


def words(text):
    return re.findall(r"[a-z']+", text.lower())


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (word != other)))
        previous = current
    return previous[-1]


async def trial(client, model, root, case, pad_ms, repeat):
    voice, number = case
    reference = (root / 'sentences.txt').read_text().splitlines()[number - 1]
    with wave.open(str(root / f'{voice}_{number:02d}.wav'), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Expected 16kHz mono PCM16')
        pcm = source.readframes(source.getnframes())
    config = types.LiveConnectConfig(
        response_modalities=['AUDIO'],
        system_instruction='Reply with exactly one word: OK. Never say anything else.',
        input_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)))
    row = dict(voice=voice, sentence=number, pad_ms=pad_ms, repeat=repeat,
               reference_words=len(words(reference)), audio_seconds=len(pcm)/32000,
               error=None, transcript_received=False, turn_complete=False,
               first_transcript_after_end_ms=None, first_audio_after_end_ms=None,
               transcript_before_end=False, output_bytes=0)
    heard = []
    try:
        start = time.perf_counter()
        async with client.aio.live.connect(model=model, config=config) as session:
            row['connect_ms'] = round((time.perf_counter()-start)*1000)
            end_at = None
            first_text = None
            first_audio = None

            async def receive():
                nonlocal first_text, first_audio
                while True:
                    async for message in session.receive():
                        content = message.server_content
                        if not content:
                            continue
                        if content.input_transcription and content.input_transcription.text:
                            if first_text is None:
                                first_text = time.perf_counter()
                            heard.append(content.input_transcription.text)
                        if content.model_turn:
                            for part in content.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    if first_audio is None:
                                        first_audio = time.perf_counter()
                                    row['output_bytes'] += len(part.inline_data.data)
                        if content.turn_complete:
                            row['turn_complete'] = True
                            return

            receiver = asyncio.create_task(receive())
            try:
                await session.send_realtime_input(activity_start=types.ActivityStart())
                padding = bytes(32 * pad_ms)
                payload = padding + pcm + padding
                started = time.perf_counter()
                for offset in range(0, len(payload), 3200):
                    await session.send_realtime_input(audio=types.Blob(
                        data=payload[offset:offset+3200], mime_type='audio/pcm;rate=16000'))
                    deadline = started + min(offset+3200, len(payload))/32000
                    await asyncio.sleep(max(0, deadline-time.perf_counter()))
                end_at = time.perf_counter()
                row['send_ms'] = round((end_at-started)*1000)
                await session.send_realtime_input(activity_end=types.ActivityEnd())
                await asyncio.wait_for(receiver, 30)
                if first_text is not None:
                    row['first_transcript_after_end_ms'] = round((first_text-end_at)*1000)
                    row['transcript_before_end'] = first_text < end_at
                if first_audio is not None:
                    row['first_audio_after_end_ms'] = round((first_audio-end_at)*1000)
            finally:
                if not receiver.done():
                    receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
    except Exception as error:
        # Avoid logging SDK exception bodies which can contain request information.
        row['error'] = type(error).__name__
    hypothesis = ''.join(heard).strip()
    row['transcript_received'] = bool(hypothesis)
    row['word_errors'] = distance(words(reference), words(hypothesis))
    row['exact'] = words(reference) == words(hypothesis)
    return row


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', default='gemini-3.8-live')
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    cases = [('Karen', 7), ('Karen', 8), ('Rishi', 8), ('Tessa', 5), ('Daniel', 5)]
    result = dict(created_at=datetime.now(timezone.utc).isoformat(), model=args.model,
                  sdk=importlib.metadata.version('google-genai'), python=platform.python_version(),
                  synthetic=True, pacing='100ms PCM chunks at real-time rate', rows=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    client = make_client()
    try:
        for repeat in range(1, args.repeats+1):
            for case in cases:
                for pad in ([0, 300] if repeat % 2 else [300, 0]):
                    row = await trial(client, args.model, args.input_dir, case, pad, repeat)
                    result['rows'].append(row)
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
                    print(f'{len(result["rows"])}/{args.repeats*len(cases)*2} {case} pad={pad} exact={row["exact"]} error={row["error"]}', flush=True)
    finally:
        await client.aio.aclose()


if __name__ == '__main__':
    asyncio.run(main())
