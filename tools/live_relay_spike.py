"""Live 음성 중계를 운영 서버 없이 띄우는 작은 시험 서버.

담당: FE1
같이 보는 파일: server/live.py (중계 본체), tools/fake_browser_live.py (실제 Gemini로 하는 확인),
              tests/test_live_session_lifetime.py (가짜 Gemini로 하는 세션 수명 시험)

11/17에 중계 코드가 `server/live.py`로 옮겨졌다(경로 `/ws/live`, BE1 합의). 이 파일에는 로직이
없다. 운영 서버(`server/app.py`)를 켜지 않고 중계만 따로 띄우고 싶을 때 쓴다. 중계를 고칠 때는
`server/live.py`를 고친다.

운영 서버로 시험하는 것이 기본이다. 이 파일은 포트를 따로 쓰고 싶을 때만 쓴다.

    uv run uvicorn server.app:app --host 0.0.0.0 --port 8000                      # 운영 서버(/ws/live 포함)
    PYTHONPATH=. uv run uvicorn --app-dir tools live_relay_spike:app --port 8013  # 중계만

아이폰으로 시험할 때는 HTTPS 터널 주소의 `/live`를 Safari에서 연다(README의 Cloudflare 터널).
실제 Gemini로 한 번 왕복해 보려면:

    PYTHONPATH=. uv run python tools/fake_browser_live.py /tmp/q16k.wav KHD_SEODANG

설치: uv sync (websockets는 11/17에 기본 의존성으로 옮겼다)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from server.live.live import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(router)  # GET /live, WS /ws/live
