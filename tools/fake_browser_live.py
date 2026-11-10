"""브라우저 흉내: 서버 WebSocket에 16kHz PCM을 실시간으로 올리고 24kHz PCM과 글자를 받는다.

담당: FE1
같이 보는 파일: tools/live_relay_spike.py (상대편 서버)

아이폰 Safari 없이 중계 경로를 확인하기 위한 것이다. 폰처럼 100ms씩 실시간으로 보내므로,
"말이 끝난 뒤 첫 음성까지" 걸린 시간을 관람객 체감에 가깝게 잴 수 있다.
실제 기기 확인을 대신하지는 못한다(마이크 권한, AudioWorklet, 재생 시작은 기기에서만 확인된다).
"""
import json, sys, time, wave
import websockets, asyncio

WAV, ARTWORK = sys.argv[1], sys.argv[2]
PORT = sys.argv[3] if len(sys.argv) > 3 else "8013"  # live_relay_spike를 띄운 포트

async def main():
    with wave.open(WAV, "rb") as w:
        pcm = w.readframes(w.getnframes()); seconds = w.getnframes()/16000
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/live", max_size=None) as ws:
        await ws.send(json.dumps({"artwork_id": ARTWORK}))
        print("서버:", await ws.recv())
        t0 = time.perf_counter()
        step = 16000*2*100//1000   # 100ms씩
        for i in range(0, len(pcm), step):
            await ws.send(pcm[i:i+step])
            await asyncio.sleep(0.1)   # 실제 폰처럼 실시간으로 보낸다
        await ws.send(json.dumps({"type": "audio_end"}))
        spoke_ended = time.perf_counter()
        print(f"말 끝 ({seconds:.1f}초 분량 실시간 전송)")

        first=None; audio=0; heard=[]; said=[]
        while True:
            msg = await ws.recv()
            if isinstance(msg, bytes):
                if first is None:
                    first = round((time.perf_counter()-spoke_ended)*1000)
                audio += len(msg)
            else:
                d = json.loads(msg)
                if d["type"]=="heard": heard.append(d["text"])
                elif d["type"]=="said": said.append(d["text"])
                elif d["type"]=="turn_complete": break
                elif d["type"]=="error": print("오류:", d); return
        print(f"\n말 끝난 뒤 첫 음성 {first} ms · 전체 {round((time.perf_counter()-spoke_ended)*1000)} ms")
        print(f"받은 오디오 {audio} bytes = 24kHz 기준 {audio/48000:.1f}초")
        print(f"[들은 질문] {''.join(heard).strip()}")
        print(f"[답변] {''.join(said).strip()}")

asyncio.run(main())
