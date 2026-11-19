"""시험이 실제 관람 기록에 쓰지 못하게 막는다. `server`를 가져오기 전에 먼저 가져온다.

`.env`에 `LIVE_VISIT_LOG=team`을 적어 두면 `server/gemini_client.py`가 그것을 환경 변수로
올린다. 그러면 `LIVE_VISIT_DIR`을 지정하지 않은 시험이 Live 경로를 건드릴 때마다 저장소의
`logs/`에 줄이 쌓인다. 11/19에 실측 216줄짜리 파일이 900줄로 늘어 실측과 시험 자료가 섞였다.

`load_dotenv`는 이미 있는 환경 변수를 덮지 않으므로, 여기서 먼저 임시 폴더를 박아 두면
`.env`가 무엇을 적었든 쓰기가 그 폴더로 간다. 자기 폴더를 쓰는 시험은 그대로 동작한다.
"""
import os
import tempfile

os.environ.setdefault("LIVE_VISIT_DIR", tempfile.mkdtemp(prefix="visit-log-test-"))
