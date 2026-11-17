"""Live에 사진을 넣어 '지금 보이는 작품'을 함수 호출로 받아 보는 측정 도구.

담당: FE1
같이 보는 파일: tools/live_relay_spike.py (음성 중계. 프레임 전송을 여기에 더할지 판단하려고 만든 도구),
              docs/FE1/FE1_관람분석_측정계획.md (체류 판정이 이 결과에 달려 있다),
              docs/meeting/요청_2026-11-16_관람분석.md (11/18에 가져갈 숫자)

왜 재는가:
  체류·동선을 재려면 "그 작품이 계속 보이고 있다"는 기록이 필요하다. 지금 앱은 질문할 때
  사진 한 장만 보낸다. Live는 초당 한 장까지 사진을 받으므로(공식 문서, 2026-11-17 확인)
  중계에 프레임을 얹으면 BE2의 반복 인식 없이도 체류를 셀 수 있다. 단 Live가 우리 11점을
  사진만 보고 구분하는지는 측정된 적이 없다. 그 숫자를 내는 것이 이 도구의 전부다.

무엇을 재는가:
  정답표(data/eval/recognition_answers.csv)의 사진마다 Live 세션을 열고, 프레임을 보내고,
  report_current_artwork 함수 호출로 돌아온 artwork_id를 정답과 맞춘다. Top-1 정확도와
  오답·미응답을 센다. 인식기를 만드는 것이 아니라 가능 여부만 가린다.

읽는 사람이 속지 않게:
  - 깨끗한 복제 이미지로 잰 값은 상한선이다. 전시실 프레임(기울기·반사·부분 가림·관람객)에서는
    더 떨어진다. 조건은 정답표의 condition 칸에 적고 조건별로 따로 집계한다.
  - 후보 11점을 시스템 지시문에 넣고 그중에서 고르게 한다. 전체 DB에서 찾는 것이 아니다.
    11/13에 정한 합격 기준(11점 한정 Top-1 70%)과 같은 조건이다.
  - 사진은 메모리에서만 다루고 저장하지 않는다. 저장소에 사진을 넣지 않는다(AGENTS.md).

설치: uv sync (websockets는 11/17에 기본 의존성으로 옮겼다)
실행:
    PYTHONPATH=. uv run python tools/live_frame_recognition.py --answers data/eval/recognition_answers.csv
    PYTHONPATH=. uv run python tools/live_frame_recognition.py --self-test   # 프레임 전송 경로만 확인
"""
import argparse
import asyncio
import csv
import importlib.metadata
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google.genai import types

from server.content import load_artworks
from server.gemini_client import make_client

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-3.8-live")
ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = "unknown"

# 모델이 답을 말로 하지 않고 이 함수로 돌려주게 한다. Live는 음성으로 답하면서도 함수를 부를 수 있다
# (공식 문서: ai.google.dev/gemini-api/docs/live-tools, 2026-11-17 확인).
REPORT_TOOL = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="report_current_artwork",
    description="Report which artwork from the provided list is currently visible in the camera frame.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "artwork_id": types.Schema(type=types.Type.STRING, description='One id from the list, or "unknown".'),
            "confidence": types.Schema(type=types.Type.STRING, description="high, medium or low."),
        },
        required=["artwork_id"],
    ))])


def candidate_block(artworks):
    """후보 11점의 ID와 영문 제목만 준다. 사실 설명은 넣지 않는다(인식만 재는 것이므로)."""
    return "\n".join(f"- {art_id}: {art['title_en']}" for art_id, art in artworks.items())


def instruction(artworks):
    return (
        "You identify which artwork a museum visitor's camera is pointed at.\n"
        "The exhibition contains exactly these works:\n"
        f"{candidate_block(artworks)}\n\n"
        "When you receive an image, call report_current_artwork exactly once with the id of the work "
        f'in the image. If the image shows none of them, or you cannot tell, pass "{UNKNOWN}". '
        "Never guess between two works: pass unknown instead. Do not describe the image out loud."
    )


async def ask_one(client, artworks, jpeg, modality, timeout_s, settle_s):
    """사진 한 장을 보내고 함수 호출로 돌아온 artwork_id를 받는다. 돌려주는 값은 측정 기록 한 줄."""
    config = types.LiveConnectConfig(
        response_modalities=[modality],
        system_instruction=instruction(artworks),
        tools=[REPORT_TOOL],
    )
    row = {"reported": None, "confidence": None, "said": "", "error": None, "first_reply_ms": None}
    started = time.perf_counter()
    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            row["connect_ms"] = round((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            # 폰이 보내는 것과 같은 모양으로 프레임 한 장을 넣는다(권장 768px, image/jpeg).
            await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
            # 실시간 입력은 흘려보내는 것이라 바로 질문하면 모델이 사진을 못 본 채로 답한다.
            # 2026-11-17 확인: 대기 없이 물으면 "NO IMAGE", 1초 기다리면 그림을 정확히 설명했다.
            await asyncio.sleep(settle_s)
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="Which artwork is in view?")]),
                turn_complete=True)

            async def read():
                async for message in session.receive():
                    if message.tool_call:
                        for call in message.tool_call.function_calls or []:
                            if call.name == "report_current_artwork":
                                args = call.args or {}
                                row["reported"] = args.get("artwork_id")
                                row["confidence"] = args.get("confidence")
                                row["first_reply_ms"] = round((time.perf_counter() - started) * 1000)
                                # 함수 응답을 돌려주지 않으면 세션이 기다린다. 측정에는 결과만 필요하다.
                                await session.send_tool_response(function_responses=[types.FunctionResponse(
                                    id=call.id, name=call.name, response={"ok": True})])
                        return
                    content = message.server_content
                    if not content:
                        continue
                    if content.output_transcription and content.output_transcription.text:
                        row["said"] += content.output_transcription.text
                    for part in (content.model_turn.parts or []) if content.model_turn else []:
                        if part.text:
                            row["said"] += part.text
                    if content.turn_complete:
                        row["first_reply_ms"] = row["first_reply_ms"] or round((time.perf_counter() - started) * 1000)
                        return

            await asyncio.wait_for(read(), timeout=timeout_s)
    except asyncio.TimeoutError:
        row["error"] = f"timeout after {timeout_s}s"
    except Exception as exc:  # 측정 도구이므로 한 장이 실패해도 나머지를 계속 잰다
        row["error"] = repr(exc)
    return row


def read_answers(path, images_dir):
    """정답표를 읽어 (사진 경로, 정답 ID, 조건) 목록으로 돌려준다. 사진이 없으면 알려 주고 멈춘다."""
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if not rows:
        raise SystemExit(
            f"{path.relative_to(ROOT)}에 행이 없습니다. 사진을 모으고 photo_file·artwork_id·condition을 채운 뒤\n"
            "다시 실행하세요. condition에는 clean(복제 이미지)·gallery(전시실 촬영) 같은 값을 적습니다.")
    out = []
    for row in rows:
        photo = Path(row["photo_file"])
        if not photo.is_absolute():
            photo = (images_dir or path.parent) / photo
        if not photo.exists():
            raise SystemExit(f"사진이 없습니다: {photo}\n--images 로 사진 폴더를 알려 주세요.")
        out.append((photo, row["artwork_id"].strip(), (row.get("condition") or "").strip() or "unspecified"))
    return out


async def run(items, modality, timeout_s, out_path, settle_s):
    artworks = load_artworks()
    client = make_client()
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": LIVE_MODEL,
        "sdk": importlib.metadata.version("google-genai"),
        "modality": modality,
        "frame_settle_s": settle_s,
        "candidates": sorted(artworks),
        "note": "후보 목록을 주고 그중에서 고르게 한 Top-1 측정이다. 전체 DB 검색이 아니다.",
        "rows": [],
    }
    for photo, expected, condition in items:
        row = await ask_one(client, artworks, photo.read_bytes(), modality, timeout_s, settle_s)
        row.update(photo=photo.name, expected=expected, condition=condition)
        row["correct"] = row["reported"] == expected
        result["rows"].append(row)
        mark = "O" if row["correct"] else ("-" if row["reported"] in (None, UNKNOWN) else "X")
        print(f"{mark} {photo.name} [{condition}] 정답={expected} 응답={row['reported']} "
              f"{row['first_reply_ms']}ms {row['error'] or ''}")

    print()
    for condition in sorted({r["condition"] for r in result["rows"]}):
        rows = [r for r in result["rows"] if r["condition"] == condition]
        correct = sum(r["correct"] for r in rows)
        counts = Counter("정답" if r["correct"] else "미응답" if r["reported"] in (None, UNKNOWN) else "오답"
                         for r in rows)
        print(f"[{condition}] Top-1 {correct}/{len(rows)} ({correct / len(rows):.0%}) · "
              + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print("\n이 값은 후보 11점 안에서의 Top-1이다. 조건이 clean이면 상한선이며 전시실 프레임은 더 낮다.")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    shown = out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path
    print(f"기록: {shown}")


def self_test_jpeg():
    """사진이 없을 때 프레임 전송 경로만 확인하려고 쓰는 합성 이미지(작품 사진이 아니다)."""
    import subprocess
    import struct
    import zlib
    width = height = 768
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # PNG 필터 바이트
        for x in range(width):
            rows += bytes(((x * 255) // width, (y * 255) // height, 128))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows))
           + chunk(b"IEND", b""))
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "live_frame_selftest.png"
    tmp.write_bytes(png)
    jpeg = tmp.with_suffix(".jpg")
    subprocess.run(["sips", "-s", "format", "jpeg", str(tmp), "--out", str(jpeg)],
                   check=True, capture_output=True)
    return jpeg


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", type=Path, default=ROOT / "data/eval/recognition_answers.csv")
    parser.add_argument("--images", type=Path, default=None, help="photo_file이 상대 경로일 때의 사진 폴더")
    parser.add_argument("--modality", default="AUDIO", choices=["AUDIO", "TEXT"],
                        help="AUDIO가 실제 경로와 같다. TEXT는 더 싸게 재 볼 때만")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--settle", type=float, default=1.0,
                        help="프레임을 보낸 뒤 질문하기까지 기다리는 시간(초). 0이면 모델이 사진을 못 본 채 답한다")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true",
                        help="합성 이미지 한 장으로 프레임 전송과 함수 호출 경로만 확인한다")
    args = parser.parse_args()

    if args.self_test:
        jpeg = self_test_jpeg()
        print(f"합성 이미지로 경로만 확인한다(작품 사진이 아니다): {jpeg}")
        items = [(jpeg, UNKNOWN, "self-test")]
    else:
        items = read_answers(args.answers, args.images)

    stamp = datetime.now().strftime("%Y-%m-%d")
    out = args.out or ROOT / f"data/eval/live_frame_recognition_{stamp}.json"
    asyncio.run(run(items, args.modality, args.timeout, out, args.settle))


if __name__ == "__main__":
    main()
