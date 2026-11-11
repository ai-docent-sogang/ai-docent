"""브라우저 흉내: 서버 WebSocket에 16kHz PCM을 실시간으로 올리고 24kHz PCM과 글자를 받는다.

담당: FE1
같이 보는 파일: tools/live_relay_spike.py (상대편 서버)

아이폰 Safari 없이 중계 경로를 확인하기 위한 것이다. 폰처럼 100ms씩 실시간으로 보내므로,
"말이 끝난 뒤 첫 음성까지" 걸린 시간을 관람객 체감에 가깝게 잴 수 있다.
실제 기기 확인을 대신하지는 못한다(마이크 권한, AudioWorklet, 재생 시작은 기기에서만 확인된다).

실행(시험용 음성은 맥에서 만든다. 실제 관람객 음성을 저장하지 않기 위함이다):
    say -v Samantha -o /tmp/q1.aiff "Who painted this?"
    afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/q1.aiff /tmp/q1.wav
    PYTHONPATH=. uv run python tools/fake_browser_live.py KHD_SSIREUM /tmp/q1.wav /tmp/q2.wav

WAV를 여러 개 주면 한 연결에서 연달아 묻는다. 반드시 두 개 이상으로 확인한다. 한 번만 묻는
시험은 통과하면서 두 번째 질문부터 막히는 결함이 실제로 있었다(11/12, live_relay_spike.py 주석).
"""
import json, sys, time, wave
import websockets, asyncio

ARTWORK = sys.argv[1]
# WAV를 여러 개 주면 한 연결에서 연달아 묻는다. 한 번만 묻는 시험으로는 11/12에 겪은
# "두 번째 질문부터 답이 오지 않는" 결함을 잡을 수 없었다. 그래서 여러 턴이 기본이다.
WAVS = [a for a in sys.argv[2:] if not a.startswith("--") and a.endswith(".wav")]
PORT = next((a.split("=")[1] for a in sys.argv if a.startswith("--port=")), "8013")
# --slow 또는 --slow=초(기본 0.4초): 느린 폰을 흉내 내어 조각마다 그만큼 쉰다.
# 폰 전송이 느릴 때 중계가 Gemini 읽기를 멈추지 않는지 보는 용도다.
SLOW = next((float(a.split("=")[1]) if "=" in a else 0.4 for a in sys.argv if a.startswith("--slow")), 0)

async def main():
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/live", max_size=None) as ws:
        await ws.send(json.dumps({"artwork_id": ARTWORK}))
        print("서버:", await ws.recv())

        for turn, path in enumerate(WAVS, 1):
            with wave.open(path, "rb") as w:
                pcm = w.readframes(w.getnframes())
                seconds = w.getnframes() / 16000

            await ws.send(json.dumps({"type": "speech_start"}))   # 버튼 누름
            step = 16000 * 2 * 100 // 1000                        # 100ms씩
            for i in range(0, len(pcm), step):
                await ws.send(pcm[i:i + step])
                await asyncio.sleep(0.1)                          # 실제 폰처럼 실시간으로 보낸다
            await ws.send(json.dumps({"type": "speech_end"}))     # 버튼 뗌
            spoke_ended = time.perf_counter()

            first = None; audio = 0; heard = []; said = []
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=45)
                    if isinstance(msg, bytes):
                        if SLOW:
                            await asyncio.sleep(SLOW)  # 조각마다 지연 = 느린 폰
                        if first is None:
                            first = round((time.perf_counter() - spoke_ended) * 1000)
                        audio += len(msg)
                    else:
                        d = json.loads(msg)
                        if d["type"] == "heard": heard.append(d["text"])
                        elif d["type"] == "said": said.append(d["text"])
                        elif d["type"] == "turn_complete": break
                        elif d["type"] == "error": print("오류:", d); return
            except asyncio.TimeoutError:
                print(f"턴 {turn}: 45초 안에 답이 오지 않았다. 중계가 Gemini를 계속 읽고 있는지 확인한다.")
                return

            print(f"\n턴 {turn} ({seconds:.1f}초 질문): 말 끝난 뒤 첫 음성 {first} ms · "
                  f"음성 {audio/48000:.1f}초 ({audio} bytes)")
            print(f"  [들은 질문] {''.join(heard).strip()}")
            print(f"  [답변] {''.join(said).strip()}")

        print(f"\n{len(WAVS)}턴 모두 한 연결에서 성공")
        if SLOW:
            print(f"(--slow={SLOW}: 느린 폰을 흉내 낸 결과)")


asyncio.run(main())
