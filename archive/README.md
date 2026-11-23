# archive: 끝난 실험과 지난 문서

지금 도슨트 운영(Live 서버와 폰 화면)과 관람 분석에는 쓰지 않는 파일입니다. 지우지 않고 이곳에 둡니다. 평소에는 열지 않아도 됩니다.

**규칙.** 원래 경로를 그대로 따라 둡니다. `tools/compare_modes.py`는 `archive/tools/compare_modes.py`에 있습니다. 같이 옮긴 파일끼리의 상대 경로와 링크가 그대로 맞습니다.

**되돌리기.** 쓸 일이 생기면 한 줄로 제자리로 옮깁니다.

```bash
git mv archive/tools/compare_modes.py tools/compare_modes.py
```

**실행.** 옮긴 스크립트는 저장소 최상위에서 돌립니다. 결과 파일도 `archive/` 아래에 쌓입니다.

```bash
PYTHONPATH=. uv run python archive/tools/compare_modes.py --help
```

## 무엇을 옮겼나

네 묶음이고, 각 묶음의 결론은 남아 있는 문서에 있습니다.

| 묶음 | 옮긴 것 | 결론이 있는 곳 |
| --- | --- | --- |
| 음성 실험(11/11) | `experiments/voice/` 전체, `data/eval/voice_60_recovered.json`, `voice_boundary_2026-11-11.json`, `voice_output_2026-11-11.json`, `docs/FE1/FE1_음성_실험_2026-11-11.md` | [음성 비교](../docs/FE1/FE1_음성_비교.md)가 이 기록을 가리킵니다. 말 앞뒤 300ms 무음은 Live 중계에 이미 들어 있습니다 |
| 방식 비교(11/11) | `tools/compare_modes.py`, `data/eval/mode_comparison*.csv` 6개, `tools/live/probe_live_audio.py` | [결정 사항](../docs/결정사항.md) 11/11 "초기 버전 대화는 Gemini Live API로 한다" |
| `/api/ask` 폐기(11/23) | `server/pre_live/ask.py`, `tests/pre_live/test_ask.mjs`, `data/eval/ask_latency.csv`, `docs/FE1/FE1_응답시간_측정.md` | [결정 사항](../docs/결정사항.md) 11/23. `static/api.js`의 `postAsk`는 지웠다(`git log -S postAsk`로 복원). 화면이 11/17부터 안 불렀고 입력원이던 브라우저 STT도 쓰지 않는다 |
| 날짜가 지난 문서 | `docs/meeting/`의 11/11 회의록, 11/12 작업 안내, 11/16 관람 분석 요청 | 정한 것은 [결정 사항](../docs/결정사항.md)의 표가 이 문서들을 근거로 가리킵니다 |

## 옮긴 이유 (세 가지를 모두 만족한 것만)

1. **운영에 올라오지 않는다.** `server/app.py`에서 시작하는 import 닫힘과 화면(`static/*.html`)이 불러오는 스크립트 어디에도 이 파일을 가져오는 곳이 없습니다. 이 파일들을 언급하는 곳은 머리 주석과 문서뿐입니다.
2. **열린 할 일이 가리키지 않는다.** [진행상황](../docs/진행상황.md)의 미완료 항목(`- [ ]`)이 이 파일들을 부르지 않습니다.
3. **끝난 일의 산출물이다.** 11/11에 방식과 음성을 정했고, 이 파일들은 그때의 실험 도구와 결과입니다.

`/api/ask` 묶음만 예외입니다. 서버가 라우터로 올리고 있어 1번을 만족하지 않았습니다. 부르는 곳이 없어서 11/23에 폐기를 결정하고 옮겼습니다.

## 옮기지 않은 것과 이유

"지금 운영 경로에 안 올라온다"만으로는 옮기지 않았습니다. 아래는 쓰임이 남아 있거나 판단이 필요해 제자리에 둡니다.

| 파일 | 지금 상태 | 두는 이유 |
| --- | --- | --- |
| `server/pre_live/turn.py`, `docent_reply.py`, `static/pre_live/audio.js` | 화면이 Live 연결에 실패하면(`onFallback`) 누르고 말하기로 돌아가 이 경로를 씁니다 | Live 장애 때의 안전망입니다 |
| `static/pre_live/stt.js`, `tests/pre_live/test_stt.mjs` | 화면이 불러오지 않습니다 | "브라우저 STT를 시연에서 쓸지" 팀 결정이 열려 있습니다 |
| `server/recognition.py`, `artwork_crop.py`, `artwork_recognizer.py`, `catalog.py`, `tools/build_*.py`, `data/reference/`, `data/kb/`, `data/incoming/` | 서버에 아직 연결하지 않았습니다 | BE2가 진행 중인 작품 인식입니다. 인식 합격 기준(Top-1 70%)이 남아 있습니다 |
| `server/logs.py` | 비어 있는 자리입니다 | BE2 담당 자리로 정해 둔 파일입니다 |
| `data/scenarios/`, `data/comparison_extended.csv`, `glasses/` | 서버가 읽지 않습니다 | FE3·FE2가 채우는 중인 자료입니다 |
| `docs/meeting/안내_2026-11-19.md` | 지난 문서입니다 | 11/19 운영 페이지·질문 라벨 안내이고 그 브랜치(`dohyeok/ops-page`)가 아직 main에 없습니다 |

**`ask.py`를 되돌릴 때.** `archive/tools/compare_modes.py`와 `archive/tools/live/probe_live_audio.py`는 `server.pre_live.ask`와 `server.prompts.ASK_INSTRUCTION`을 가져옵니다. 이 두 도구를 돌리려면 `ask.py`를 `server/pre_live/`로 되돌려야 합니다. `ASK_INSTRUCTION`은 `server/prompts.py`에 남겨 두었습니다(BE1 파일이라 지우지 않았고, 쓰는 곳은 이 두 도구뿐입니다).

옮길지 말지는 담당자가 정합니다. 옮기기로 하면 위 규칙대로 `archive/`에 같은 경로로 `git mv` 하면 됩니다.
