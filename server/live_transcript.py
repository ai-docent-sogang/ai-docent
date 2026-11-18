"""Live 답변 자막 정리와 받아쓰기의 비교 작품 찾기. 담당: FE1.

함수 호출·모델 속 글을 자막에 내보내지 않고, 전달받은 검증 비교쌍에서만 제목을 찾는다.
"""
import re
import unicodedata

# 답변 받아쓰기에 섞여 오는 표시. 11/18 실측: 추임새에 침묵하려던 턴의 받아쓰기가 "<no speech>{pause}"나
# 폭 없는 문자(U+200B)만으로 왔다. 그대로 보내면 폰의 도슨트 말풍선에 그 글자가 뜬다.
SAID_MARKUP = re.compile(r"<no speech>|\{pause\}|[\u200b\u200c\u200d\ufeff]")


def clean_said(text):
    """받아쓰기 조각에서 말이 아닌 표시를 뺀다. 남는 말이 없으면 빈 문자열."""
    cleaned = SAID_MARKUP.sub("", text)
    return cleaned if cleaned.strip() else ""


# 답변 받아쓰기 끝에 섞여 오는 모델 속 글. 말소리에는 없고 받아쓰기 길로만 온다.
# 11/18 실측(gemini-3.8-live, handsfree 인사 턴, 포트 8055):
#   "...art you enjoy?---\n(No function call needed, per instructions to greet first.)---"
#   "...art you enjoy. =========================================="
#   "...do you usually enjoy? -=call:report_current_artwork{artwork_id:unknown…"(멘토 전달본 증상)
# 가로줄·등호가 이어진 토막과 함수 이름은 도슨트가 입으로 낼 말이 아니다(지시문도 함수 이름을
# 소리 내어 읽지 말라고 적어 둔다). 이것이 보이면 그 턴의 남은 받아쓰기는 폰에 보내지 않고
# 관람 기억에도 넣지 않는다. 서버 로그에는 왜 걸렀는지 아는 데 필요한 앞부분만 적는다.
LEAK_MARK = re.compile(r"-=|=-|[-=]{3,}|report_current_artwork|report_comparison")
# 로그에 찍는 앞부분의 길이. 걸러 낸 글은 늘 표시(LEAK_MARK)로 시작하므로 이 길이면 어떤
# 표시였는지 다 보인다. 가장 긴 표시가 report_current_artwork(22자)다.
LEAK_LOG_CHARS = 32
# 조각이 끊겨 와도 놓치지 않게, 표시의 앞부분으로 끝나는 꼬리는 다음 조각까지 들고 있는다.
LEAK_WORDS = ("-=", "=-", "---", "report_current_artwork", "report_comparison")


def leak_hold(text):
    """다음 조각과 이어 봐야 표시인지 알 수 있는 꼬리의 길이."""
    for n in range(min(len(text), max(len(w) for w in LEAK_WORDS) - 1), 0, -1):
        tail = text[-n:]
        if any(len(w) > n and w.startswith(tail) for w in LEAK_WORDS):
            return n
    return 0


def feed_said(state, chunk):
    """받아쓰기 조각을 넣고 지금 폰에 보낼 말을 돌려준다. 속 글이 시작되면 그 턴은 더 보내지 않는다."""
    if state["said_leak"]:
        state["said_leak"] += chunk
        return ""
    buf = state["said_hold"] + chunk
    found = LEAK_MARK.search(buf)
    if found:
        state["said_hold"] = ""
        state["said_leak"] = buf[found.start():]
        return clean_said(buf[:found.start()])
    hold = leak_hold(buf)
    state["said_hold"] = buf[len(buf) - hold:] if hold else ""
    return clean_said(buf[:len(buf) - hold])


def flush_said(state):
    """턴이 끝났다. 들고 있던 말을 내보내고, 걸러 낸 것이 있으면 로그에 남긴다."""
    rest = clean_said(state["said_hold"])
    state["said_hold"] = ""
    if state["said_leak"]:
        # 표시 뒤에는 도슨트가 관람객에게 한 말이 이어져 있다. 배포할 때 이 출력을 파일로
        # 넘기면 그 말이 저장되므로(AGENTS.md: 음성은 처리에만 쓰고 저장하지 않는다)
        # 표시 부분만 찍고 나머지는 길이만 적는다.
        head = state["said_leak"][:LEAK_LOG_CHARS]
        hidden = len(state["said_leak"]) - len(head)
        print(f"[live] 모델 속 글이 답변 받아쓰기에 섞여 와서 걸러 냈다: {head!r}"
              + (f" + 뒤에 {hidden}자" if hidden else ""))
        state["said_leak"] = ""
    return rest


# ── 받아쓰기로 비교 찾기 (11/18 실측: Live가 비교를 말하면서 report_comparison을 부르지 않은 턴이 있었다) ──
ARTICLES = {"the", "a", "an"}
SHORT_TITLE_CHARS = 10   # 이보다 짧거나 한 단어인 제목은 흔한 말과 겹칠 수 있어 작가 이름도 함께 나와야 인정한다


def normalize_words(text):
    """대소문자·악센트·따옴표·문장부호·관사 차이를 없앤 ' 단어 단어 ' 꼴(앞뒤 공백은 단어 경계용)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", text).split() if w not in ARTICLES]
    return " " + " ".join(words) + " "


def title_variants(title):
    """비교쌍 제목에서 관람객에게 말할 법한 이름들을 뽑는다.

    예: "Hokusai Sketchbooks (Denshin kaishu: Hokusai manga), first volume"
        → "Hokusai Sketchbooks", "Denshin kaishu", "Hokusai manga"
        "South Wind, Clear Sky (Gaifū kaisei), also known as Red Fuji, from the series ..."
        → "South Wind, Clear Sky", "Gaifū kaisei", "Red Fuji" (연작 이름은 그 작품이 아니므로 뺀다)
    """
    variants = [title.split("(")[0]]
    for inner in re.findall(r"\(([^)]*)\)", title):
        variants += inner.split(":")
    aka = re.search(r"also known as (.+?)(?:,| from |$)", title)
    if aka:
        variants.append(aka.group(1))
    out = []
    for v in variants:
        v = re.split(r",\s*(?:first|second|third) volume|\bfrom the series\b", v)[0]
        norm = normalize_words(v)
        if norm.strip() and norm not in out:
            out.append(norm)
    return out


def artist_words(artist):
    """작가 이름에서 알아볼 단어(4자 이상, Elder 같은 말 제외). "Pieter Bruegel the Elder (…)" → pieter, bruegel."""
    name = normalize_words(artist.split("(")[0])
    return [w for w in name.split() if len(w) >= 4 and w not in {"elder", "younger"}]


def comparison_in_transcript(said, artwork_id, verified_comparisons):
    """답변 받아쓰기에 지금 작품의 검증된 비교쌍 제목이 나오면 그 comparison_id(가장 먼저 나온 것).

    다른 작품의 비교쌍은 보지 않는다. 짧은 제목은 작가 이름도 함께 나와야 한다.
    """
    text = normalize_words(said)
    found = []
    for cid, pair in verified_comparisons.items():
        if pair["artwork_id"] != artwork_id:
            continue
        for variant in title_variants(pair["foreign_title"]):
            at = text.find(variant)
            if at < 0:
                continue
            short = len(variant.strip()) < SHORT_TITLE_CHARS or len(variant.split()) < 2
            if short and not any(f" {w} " in text for w in artist_words(pair["foreign_artist"])):
                continue
            found.append((at, cid))
    return min(found)[1] if found else ""


