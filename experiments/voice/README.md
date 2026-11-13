# 음성 실험 실행하기

저장소 최상위에서 아래 명령을 실행한다. API 키는 최상위 `.env`의 `GEMINI_API_KEY`를 사용한다. Live API 호출에는 요금이 발생한다. 설치는 `uv sync --extra live`를 따른다.

## 코드 찾기

| 파일 | 용도 |
| --- | --- |
| `generate_inputs.py` | macOS 설치 음성 6종으로 고정 대본 10개씩 생성 |
| `voice_boundary_experiment.py` | 취약 문장 5개를 무음 보정 전후 각 5회, 총 50회 시험 |
| `voice_output_experiment.py` | Kore·Puck·Aoede를 각 5회 호출하고 첫 회 청취 WAV 생성 |
| `sentences.txt` | 합성 입력에 사용하는 고정 영어 대본 10개 |
| `archive/stt_live.py` | 이전 세션의 Live 60개 비교 코드 원본 |
| `archive/stt_turn.py` | 이전 세션의 `/api/turn` 60개 비교 코드 원본 |

`archive`는 당시 측정 방식을 확인하기 위한 원본이다. 입력 위치를 스크립트 옆 `stt/`로 가정한다. Live 원본은 음성을 일괄 전송하므로 현재 실시간 전송 시험과 시간 값을 직접 비교하지 않는다.

서버 중계 시험 코드는 [`tools/live_relay_spike.py`](../../tools/live_relay_spike.py), 단일 음성 확인은 [`tools/probe_live_audio.py`](../../tools/probe_live_audio.py), 브라우저 모의 클라이언트는 [`tools/fake_browser_live.py`](../../tools/fake_browser_live.py)에 있다.

## 합성 입력 생성하기

macOS에서 Samantha·Daniel·Karen·Moira·Rishi·Tessa 음성이 설치된 상태로 실행한다. `say -v '?'`로 설치 목록을 확인할 수 있다.

```sh
.venv/bin/python experiments/voice/generate_inputs.py /private/tmp/docent-voice-inputs
```

`sentences.txt`와 16kHz 모노 PCM16 WAV 60개가 생성된다. 실제 사람의 마이크 음성을 녹음하지 않는다. OS 음성 버전과 읽기 속도에 따라 이전 세션의 파일과 파형이 달라질 수 있다.

## STT 경계 재시험하기

```sh
PYTHONPATH=. .venv/bin/python experiments/voice/voice_boundary_experiment.py \
  /private/tmp/docent-voice-inputs /private/tmp/docent-voice-boundary.json
```

매 요청 후 결과 JSON을 저장한다. `--repeats 1`이면 10건만 실행한다. 오류, 단어 오류 수, 완전 일치, 완료 신호, 첫 받아쓰기와 첫 음성 조각 시간을 기록한다. 입력 음성과 받아쓰기 원문은 결과 JSON에 복사하지 않는다.

## 출력 음성 비교하기

```sh
PYTHONPATH=. .venv/bin/python experiments/voice/voice_output_experiment.py \
  /private/tmp/docent-voice-listening
```

`results.json`과 `Kore.wav`, `Puck.wav`, `Aoede.wav`가 생성된다. `--repeats 1`이면 3건만 실행한다. WAV는 첫 반복이 정상 완료되고 출력 형식이 24kHz PCM인 경우에만 저장한다. 고정 합성 대본을 사용하며 관람객 음성은 포함하지 않는다.

기존 결과 경로와 겹치면 JSON과 WAV를 덮어쓸 수 있으므로 새 출력 경로를 사용한다.

## 결과 확인하기

2026-11-11 측정 결과는 [`docs/FE1_음성_실험_2026-11-11.md`](../../docs/FE1_음성_실험_2026-11-11.md)에 정리했다. 행별 점수와 측정값은 다음 파일에 있다.

- [`voice_60_recovered.json`](../../data/eval/voice_60_recovered.json)
- [`voice_boundary_2026-11-11.json`](../../data/eval/voice_boundary_2026-11-11.json)
- [`voice_output_2026-11-11.json`](../../data/eval/voice_output_2026-11-11.json)

모델·SDK 공식 확인 근거와 측정 한계는 실험 기록을 따른다. 실제 관람객 음성은 입력 폴더에 넣지 않는다.
