"""브라우저 흉내: 서버 WebSocket에 16kHz PCM을 실시간으로 올리고 24kHz PCM과 글자를 받는다.

담당: FE1
같이 보는 파일: tools/live/live_relay_spike.py (상대편 서버)

아이폰 Safari 없이 중계 경로를 확인하기 위한 것이다. 폰처럼 100ms씩 실시간으로 보내므로,
"말이 끝난 뒤 첫 음성까지" 걸린 시간을 관람객 체감에 가깝게 잴 수 있다.
실제 기기 확인을 대신하지는 못한다(마이크 권한, AudioWorklet, 재생 시작은 기기에서만 확인된다).

실행(시험용 음성은 맥에서 만든다. 실제 관람객 음성을 저장하지 않기 위함이다):
    say -v Samantha -o /tmp/q1.aiff "Who painted this?"
    afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/q1.aiff /tmp/q1.wav
    PYTHONPATH=. uv run python tools/live/fake_browser_live.py KHD_SSIREUM /tmp/q1.wav /tmp/q2.wav

WAV를 여러 개 주면 한 연결에서 연달아 묻는다. 반드시 두 개 이상으로 확인한다. 한 번만 묻는
시험은 통과하면서 두 번째 질문부터 막히는 결함이 실제로 있었다(11/11, live_relay_spike.py 주석).

handsfree 모드(11/18, 버튼 없는 대화):
    PYTHONPATH=. uv run python tools/live/fake_browser_live.py --handsfree --frame=/path/ssireum.jpg \
        q1.wav q2.wav --port=8091
    버튼 신호를 보내지 않는다. 연결 내내 100ms마다 소리를 보낸다(질문 WAV를 실시간 속도로 흘리고,
    그 밖에는 무음). 사진은 3초마다 보낸다. 먼저 Live의 인사 턴을 받고, 그 뒤 WAV마다 한 턴씩 묻는다.
    작품 ID 인자는 받지 않는다(Live가 사진으로 알아본다). --country=France 로 프로필을 줄 수 있다.
    --resume-after=N: N번째 질문 뒤에 폰 WS를 닫고, 같은 session_id와 "resume": true로 다시 붙어
    남은 질문을 잇는다(폰 화면 꺼짐·네트워크 끊김 흉내). 닫은 뒤 ready까지 걸린 시간과 resumed를 본다.
    --backchannel=a.wav,b.wav: 질문을 다 한 뒤 추임새("Mm-hmm." 등)를 하나씩 흘리고 8초씩 지켜본다.
    도슨트가 말하지 않아야 정상이다(11/18 실기기에서 추임새에도 답했다). 들은 말과 답을 그대로 적는다.
"""
import base64, json, sys, time, wave
import websockets, asyncio

HANDSFREE = "--handsfree" in sys.argv
FRAME = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--frame=")), None)
COUNTRY = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--country=")), "")
BACKCHANNEL = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--backchannel=")), [])
RESUME_AFTER = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--resume-after=")), 0)
ARTWORK = None if HANDSFREE else sys.argv[1]
# WAV를 여러 개 주면 한 연결에서 연달아 묻는다. 한 번만 묻는 시험으로는 11/11에 겪은
# "두 번째 질문부터 답이 오지 않는" 결함을 잡을 수 없었다. 그래서 여러 턴이 기본이다.
WAVS = [a for a in sys.argv[2:] if not a.startswith("--") and a.endswith(".wav")]
PORT = next((a.split("=")[1] for a in sys.argv if a.startswith("--port=")), "8013")
# --slow 또는 --slow=초(기본 0.4초): 느린 폰을 흉내 내어 조각마다 그만큼 쉰다.
# 폰 전송이 느릴 때 중계가 Gemini 읽기를 멈추지 않는지 보는 용도다.
SLOW = next((float(a.split("=")[1]) if "=" in a else 0.4 for a in sys.argv if a.startswith("--slow")), 0)

async def main():
    if HANDSFREE:
        return await handsfree()
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



parts_last = [None]   # 추임새는 마지막 연결에서만 흘린다


async def handsfree():
    """버튼 없이 계속 소리를 흘리며 묻는다. --resume-after가 있으면 중간에 끊고 다시 붙는다."""
    t0 = time.perf_counter()
    if RESUME_AFTER and 0 < RESUME_AFTER < len(WAVS):
        parts = [WAVS[:RESUME_AFTER], WAVS[RESUME_AFTER:]]
    else:
        parts = [WAVS]
    session_id, closed_at, turn_no = "", None, 0
    parts_last[0] = parts[-1]
    for i, wavs in enumerate(parts):
        result = await handsfree_connection(wavs, session_id, resume=i > 0, closed_at=closed_at, turn_no=turn_no)
        if result is None:
            return
        session_id, closed_at = result, time.perf_counter()
        turn_no += len(wavs)
        if i + 1 < len(parts):
            print(f"\n--- 폰 WS를 닫았다(session_id {session_id[:8]}…). 같은 관람으로 다시 붙는다 ---")
    print(f"\n{len(WAVS)}턴 모두 성공 · 연결 {len(parts)}개 (전체 {time.perf_counter() - t0:.0f}초)")


async def handsfree_connection(wavs, session_id, resume, closed_at, turn_no):
    """연결 하나에서 묻는다. 성공하면 session_id를 돌려준다."""
    frame = open(FRAME, "rb").read() if FRAME else None
    step = 16000 * 2 * 100 // 1000                      # 100ms
    silence = b"\x00\x00" * (step // 2)
    pending = bytearray()                                 # 아직 보내지 않은 질문 소리
    spoken = asyncio.Event()                              # 질문 소리를 다 보냈을 때
    events = asyncio.Queue()                              # 서버에서 받은 것 (도착 시각, 내용)

    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/live", max_size=None) as ws:
        hello = {"mode": "handsfree", "session_id": session_id,
                 "profile": {"country": COUNTRY, "age_group": "", "language": "en"}}
        if resume:
            hello["resume"] = True
        await ws.send(json.dumps(hello))
        ready = json.loads(await ws.recv())
        print("서버:", ready)
        if closed_at is not None:
            print(f"  (앞 WS를 닫은 뒤 ready까지 {round((time.perf_counter() - closed_at) * 1000)} ms)")
        if ready.get("type") != "ready":
            return None

        async def mic():
            """폰 마이크처럼 100ms마다 보낸다. 질문이 있으면 질문을, 없으면 무음을."""
            while True:
                if pending:
                    chunk = bytes(pending[:step]); del pending[:step]
                    if not pending:
                        spoken.set()
                else:
                    chunk = silence
                await ws.send(chunk)
                await asyncio.sleep(0.1)

        async def camera():
            while frame:
                await ws.send(json.dumps({"type": "frame", "jpeg": base64.b64encode(frame).decode()}))
                await asyncio.sleep(3)

        async def reader():
            async for msg in ws:
                now = time.perf_counter()
                events.put_nowait((now, msg if isinstance(msg, bytes) else json.loads(msg)))

        tasks = [asyncio.create_task(f()) for f in (mic, camera, reader)]

        async def one_turn(label, since):
            """턴 하나를 받는다. 음성이 나온 뒤의 turn_complete까지(함수 호출만 있는 중간 턴은 넘긴다)."""
            first = None; audio = 0; heard = []; said = []; notes = []
            while True:
                at, d = await asyncio.wait_for(events.get(), timeout=60)
                if isinstance(d, bytes):
                    if first is None:
                        first = round((at - since) * 1000)
                    audio += len(d)
                    continue
                kind = d.get("type")
                if kind == "heard": heard.append(d["text"])
                elif kind == "said": said.append(d["text"])
                elif kind in ("artwork", "comparison", "interrupted", "reconnecting", "reconnected"):
                    notes.append(f"{round((at - since) * 1000)}ms {json.dumps(d, ensure_ascii=False)}")
                elif kind == "error":
                    print("오류:", d); raise SystemExit(1)
                elif kind == "turn_complete" and audio:
                    break
            print(f"\n{label}: 첫 음성 {first} ms · 음성 {audio/48000:.1f}초")
            for n in notes:
                print(f"  [알림] {n}")
            print(f"  [들은 말] {''.join(heard).strip()}")
            print(f"  [답변] {''.join(said).strip()}")

        try:
            if not ready.get("resumed"):
                # 새 관람이면 인사, 다시 붙었는데 대화를 잃었으면 "돌아왔다"는 한마디가 먼저 온다.
                await one_turn("인사(연결 직후, 기준=ready 받은 시각)" if not resume
                               else "대화를 잇지 못함 — 돌아왔다는 말(기준=ready 받은 시각)", time.perf_counter())
            for turn, path in enumerate(wavs, turn_no + 1):
                await asyncio.sleep(1.5)                  # 사진이 들어갈 여유(1초 함정) + 사람의 쉼
                with wave.open(path, "rb") as w:
                    pcm = w.readframes(w.getnframes())
                    seconds = w.getnframes() / 16000
                while not events.empty():                 # 앞 턴의 남은 조각은 버린다
                    events.get_nowait()
                spoken.clear(); pending.extend(pcm)
                await spoken.wait()
                ended = time.perf_counter() + 0.1        # 마지막 조각이 나간 시각
                await one_turn(f"턴 {turn} ({seconds:.1f}초 질문, 기준=질문 소리를 다 보낸 시각)", ended)
            for path in (BACKCHANNEL if wavs is parts_last[0] else []):
                await asyncio.sleep(1.5)
                with wave.open(path, "rb") as w:
                    pcm = w.readframes(w.getnframes())
                while not events.empty():
                    events.get_nowait()
                spoken.clear(); pending.extend(pcm)
                await spoken.wait()
                ended = time.perf_counter() + 0.1
                audio = 0; first = None; heard = []; said = []; kinds = []
                # 기본 8초를 지켜보고, 답이 오면 그 음성이 폰에서 다 재생될 만큼 더 기다린다(최대 40초).
                def until():
                    if first is None:
                        return 8
                    return min(40, first / 1000 + audio / 48000 + 1.5)
                while time.perf_counter() - ended < until():
                    try:
                        at, d = await asyncio.wait_for(events.get(), timeout=max(0.05, until() - (time.perf_counter() - ended)))
                    except asyncio.TimeoutError:
                        break
                    if isinstance(d, bytes):
                        audio += len(d); first = first or round((at - ended) * 1000)
                    else:
                        kinds.append(d.get("type"))
                        if d.get("type") == "heard": heard.append(d["text"])
                        if d.get("type") == "said": said.append(d["text"])
                verdict = "침묵(정상)" if not audio else f"답함 — 첫 음성 {first} ms, 음성 {audio/48000:.1f}초"
                print(f"\n추임새 {path.rsplit('/', 1)[-1]}: {verdict}")
                print(f"  [들은 말] {''.join(heard).strip()}")
                print(f"  [답변] {''.join(said).strip()}")
                print(f"  [받은 종류] {kinds}")
            return ready.get("session_id")
        except asyncio.TimeoutError:
            print("60초 안에 답이 오지 않았다. 자동 음성 감지가 말의 끝을 잡았는지 서버 로그를 본다.")
            return None
        finally:
            for t in tasks:
                t.cancel()


asyncio.run(main())
