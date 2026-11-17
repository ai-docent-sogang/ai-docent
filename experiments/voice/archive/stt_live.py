"""Live API의 입력 받아쓰기 정확도를 억양별로 잰다. 답변 음성은 받지 않는다(요금·시간 절약)."""
import asyncio, json, os, re, sys, time, wave
from google.genai import types
from server.gemini_client import make_client

S = os.path.dirname(os.path.abspath(__file__)) + "/stt"
SENTENCES = open(S + "/sentences.txt", encoding="utf-8").read().split("\n")
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa"]
MODEL = os.environ.get("STT_MODEL", "gemini-3.8-live")
# 말 경계에 넣는 무음(ms). 0이면 넣지 않는다(이전 측정과 비교용).
PAD_MS = int(os.environ.get("PAD_MS", "0"))
PAD = b"\x00\x00" * (16000 * PAD_MS // 1000)
# 특정 화자·문장만 다시 재려면 ONLY="Karen_07,Tessa_05" 형태로 준다.
ONLY = [x for x in os.environ.get("ONLY", "").split(",") if x]

def words(t):
    return re.findall(r"[a-z']+", t.lower())

def wer(ref, hyp):
    """누락·대체·삽입 합계 / 정답 단어 수 (편집 거리)."""
    r, h = words(ref), words(hyp)
    d = [[0]*(len(h)+1) for _ in range(len(r)+1)]
    for i in range(len(r)+1): d[i][0] = i
    for j in range(len(h)+1): d[0][j] = j
    for i in range(1, len(r)+1):
        for j in range(1, len(h)+1):
            d[i][j] = min(d[i-1][j]+1, d[i][j-1]+1, d[i-1][j-1] + (r[i-1] != h[j-1]))
    return d[len(r)][len(h)], len(r)

async def main():
    client = make_client()
    config = types.LiveConnectConfig(
        # gemini-3.8-live는 TEXT 출력을 지원하지 않는다. 받아쓰기 경로는 출시 모델과 같게 두고,
        # 답을 한 마디로 제한해 출력 음성 길이(=요금·시간)만 줄인다.
        response_modalities=["AUDIO"],
        system_instruction="Reply with exactly one word: OK. Never say anything else.",
        input_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)),
    )
    rows = []

    async def read_turn(session, t0):
        """한 턴을 읽는다. 제한 시간을 둬서 응답이 없으면 포기한다(세션이 비활성으로 닫히는 것을 막는다)."""
        heard, ms = [], None
        it = session.receive().__aiter__()
        while True:
            m = await asyncio.wait_for(it.__anext__(), timeout=30)
            c = m.server_content
            if c is None:
                continue
            if c.input_transcription and c.input_transcription.text:
                if ms is None:
                    ms = round((time.perf_counter() - t0) * 1000)
                heard.append(c.input_transcription.text)
            if c.turn_complete:
                return "".join(heard).strip(), ms

    for voice in VOICES:
        session_cm = None
        session = None
        for i, ref in enumerate(SENTENCES, 1):
            if ONLY and f"{voice}_{i:02d}" not in ONLY:
                continue
            if session is None:   # 첫 턴이거나 앞 턴에서 세션이 끊긴 경우
                session_cm = client.aio.live.connect(model=MODEL, config=config)
                session = await session_cm.__aenter__()
            with wave.open(f"{S}/{voice}_{i:02d}.wav", "rb") as w:
                pcm = w.readframes(w.getnframes())
            t0 = time.perf_counter()
            got, ms = "", None
            try:
                await session.send_realtime_input(activity_start=types.ActivityStart())
                if PAD:
                    await session.send_realtime_input(
                        audio=types.Blob(data=PAD, mime_type="audio/pcm;rate=16000"))
                for k in range(0, len(pcm), 3200):
                    await session.send_realtime_input(
                        audio=types.Blob(data=pcm[k:k+3200], mime_type="audio/pcm;rate=16000"))
                if PAD:
                    await session.send_realtime_input(
                        audio=types.Blob(data=PAD, mime_type="audio/pcm;rate=16000"))
                await session.send_realtime_input(activity_end=types.ActivityEnd())
                got, ms = await read_turn(session, t0)
            except (asyncio.TimeoutError, Exception) as e:
                print(f"  {voice}_{i:02d} 실패({type(e).__name__}): {e}"[:150], flush=True)
                try:
                    await session_cm.__aexit__(None, None, None)
                except Exception:
                    pass
                session = None   # 다음 턴에서 새로 연결한다
            err, total = wer(ref, got)
            rows.append({"voice": voice, "n": i, "ref": ref, "got": got,
                         "err": err, "total": total, "ms": ms})
            print(f"{voice}_{i:02d} 오류 {err}/{total} {ms}ms | {got!r}", flush=True)
        if session is not None:
            try:
                await session_cm.__aexit__(None, None, None)
            except Exception:
                pass

    out = os.environ.get("OUT", f"{S}/live_result.json")
    json.dump(rows, open(out,"w"), ensure_ascii=False, indent=1)
    err = sum(r["err"] for r in rows); tot = sum(r["total"] for r in rows)
    ok = sum(1 for r in rows if r["err"] == 0)
    print(f"\n전체 WER {err/tot*100:.1f}% ({err}/{tot}), 완전일치 {ok}/{len(rows)}")
asyncio.run(main())
