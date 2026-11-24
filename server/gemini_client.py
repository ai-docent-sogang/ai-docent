"""Gemini 클라이언트 만들기. 요청·응답 경로와 Live가 함께 쓴다 (담당 BE1).

`uv run python -m server.gemini_client --list-models`로 사용 가능한 모델을 조회한다.
`/api/turn`의 응답 생성은 `server/pre_live/docent_reply.py`에 있다.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

# 이미 설정된 환경 변수를 우선한다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def make_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY가 없습니다. 저장소 최상위의 .env에 키를 넣으세요 (.env.example 참고).")
    return genai.Client(api_key=api_key)


if __name__ == "__main__" and "--list-models" in sys.argv:
    # 모델 목록을 순회하는 동안 클라이언트 연결을 유지한다.
    client = make_client()
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name)
