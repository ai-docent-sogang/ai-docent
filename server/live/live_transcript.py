"""Live 답변 자막 필터링과 검증된 비교작 제목 매칭 (담당 FE1)."""
import re
import unicodedata

# 추임새에 응답하지 않은 턴에도 자막용 마커가 들어올 수 있다.
SAID_MARKUP = re.compile(r"<no speech>|\{pause\}|[\u200b\u200c\u200d\ufeff]")


def clean_said(text):
    """무음 마커와 폭 없는 문자를 제거한다."""
    cleaned = SAID_MARKUP.sub("", text)
    return cleaned if cleaned.strip() else ""


# 음성에는 없는 도구 호출 흔적이 자막에 섞일 수 있다(11/18 Live 실기기 측정).
LEAK_MARK = re.compile(r"-=|=-|[-=]{3,}|report_current_artwork|report_comparison")
LEAK_LOG_CHARS = 32
LEAK_WORDS = ("-=", "=-", "---", "report_current_artwork", "report_comparison")


def leak_hold(text):
    """마커가 다음 조각까지 이어질 수 있는 접미부의 길이를 반환한다."""
    for n in range(min(len(text), max(len(w) for w in LEAK_WORDS) - 1), 0, -1):
        tail = text[-n:]
        if any(len(w) > n and w.startswith(tail) for w in LEAK_WORDS):
            return n
    return 0


def feed_said(state, chunk):
    """지금 표시할 자막을 반환하고 도구 호출 마커 이후의 자막을 숨긴다."""
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
    """턴 종료 시 보류한 자막을 반환하고 필터 상태를 초기화한다."""
    rest = clean_said(state["said_hold"])
    state["said_hold"] = ""
    if state["said_leak"]:
        # 대화 원문 노출을 줄이도록 감지 위치부터 최대 32자와 나머지 길이만 기록한다.
        head = state["said_leak"][:LEAK_LOG_CHARS]
        hidden = len(state["said_leak"]) - len(head)
        print(f"[live] 모델 속 글이 답변 받아쓰기에 섞여 와서 걸러 냈다: {head!r}"
              + (f" + 뒤에 {hidden}자" if hidden else ""))
        state["said_leak"] = ""
    return rest


# Live가 report_comparison을 생략한 턴은 자막에서 비교작을 찾는다.
ARTICLES = {"the", "a", "an"}
SHORT_TITLE_CHARS = 10


def normalize_words(text):
    """표기를 정규화하고 제목을 단어 단위로 찾도록 양끝에 공백을 넣는다."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", text).split() if w not in ARTICLES]
    return " " + " ".join(words) + " "


def title_variants(title):
    """본문 제목과 괄호 속 표기·별칭을 추출한다. 권차와 연작명은 제외한다."""
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
    """작가 이름에서 제목 매칭을 보조할 4자 이상의 단어를 추출한다."""
    name = normalize_words(artist.split("(")[0])
    return [w for w in name.split() if len(w) >= 4 and w not in {"elder", "younger"}]


def comparison_in_transcript(said, artwork_id, verified_comparisons):
    """자막에 처음 등장한 현재 작품의 검증된 비교쌍 ID를 반환한다.

    짧은 제목은 일상 표현과 겹칠 수 있어 작가 이름도 함께 확인한다.
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


