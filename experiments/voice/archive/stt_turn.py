"""현재 v0 경로(/api/turn)의 받아쓰기 정확도를 같은 문장·같은 화자로 잰다.

Gemini 한 번 호출로 받아쓰기와 답변을 함께 하므로 받아쓰기만의 시간은 분리할 수 없다.
그래서 시간은 전체 왕복만 적는다(문서의 "STT 단독 시간은 미측정" 그대로).
"""
import json, os, re, sys, time, urllib.request

S = os.path.dirname(os.path.abspath(__file__)) + "/stt"
SENTENCES = open(S + "/sentences.txt", encoding="utf-8").read().split("\n")
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa"]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

def words(t): return re.findall(r"[a-z']+", t.lower())
def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = [[0]*(len(h)+1) for _ in range(len(r)+1)]
    for i in range(len(r)+1): d[i][0] = i
    for j in range(len(h)+1): d[0][j] = j
    for i in range(1, len(r)+1):
        for j in range(1, len(h)+1):
            d[i][j] = min(d[i-1][j]+1, d[i][j-1]+1, d[i-1][j-1] + (r[i-1] != h[j-1]))
    return d[len(r)][len(h)], len(r)

def post_multipart(url, fields, filename, filedata):
    b = "----docent"
    parts = []
    for k, v in fields.items():
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: audio/wav\r\n\r\n".encode() + filedata + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    return json.load(urllib.request.urlopen(req, timeout=90))

session = json.load(urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/session", b""), timeout=30))
print("세션:", session["session_id"][:8], flush=True)

rows = []
for voice in VOICES:
    for i, ref in enumerate(SENTENCES, 1):
        wav = open(f"{S}/{voice}_{i:02d}.wav", "rb").read()
        t0 = time.perf_counter()
        try:
            data = post_multipart(f"{BASE}/api/turn", {"session_id": session["session_id"]},
                                  "speech.wav", wav)
            total = round((time.perf_counter()-t0)*1000)
            got = data.get("transcript", "")
        except Exception as e:
            print(f"{voice}_{i:02d} 실패: {e!r}"[:160], flush=True)
            rows.append({"voice":voice,"n":i,"ref":ref,"got":"","err":len(words(ref)),
                         "total":len(words(ref)),"ms":None,"fail":True}); continue
        err, tot = wer(ref, got)
        rows.append({"voice":voice,"n":i,"ref":ref,"got":got,"err":err,"total":tot,"ms":total})
        print(f"{voice}_{i:02d} 오류 {err}/{tot} 왕복 {total}ms | {got!r}", flush=True)
json.dump(rows, open(f"{S}/turn_result.json","w"), ensure_ascii=False, indent=1)
