# Qwen2.5 드론 명령 LoRA 학습

이 디렉터리는 `Qwen/Qwen2.5-3B-Instruct`를 드론 명령 Dataset으로
LoRA 파인튜닝하고, 학습 전후 결과를 자동으로 비교한다.

## 실행 환경

KT Cloud A100 서버에서 저장소 루트를 기준으로 실행한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r training/requirements.txt
```

## 학습 실행

```bash
python3 -m training.train \
    --model-name Qwen/Qwen2.5-3B-Instruct \
    --dataset-dir data/dataset_v0.1 \
    --output-root training/outputs
```

현재 System Prompt와 JSON Schema가 길기 때문에 기본 최대 시퀀스 길이는
16,384 토큰이다. A100 메모리가 부족하면 먼저 배치 크기를 `1`로 줄인다.

```bash
python3 -m training.train --batch-size 1
```

학습 스크립트는 다음 순서로 동작한다.

1. Train, Validation, Test Dataset의 JSON과 Function Schema를 검증한다.
2. Test Dataset으로 원본 모델의 기준 성능을 평가한다.
3. Train과 Validation Dataset으로 LoRA 학습을 수행한다.
4. 같은 Test Dataset으로 파인튜닝 모델을 평가한다.
5. 학습 전후 비교 보고서와 실패 샘플을 저장한다.

## 출력 파일

```text
training/outputs/YYYY-MM-DD_HHMMSS/
├── training_log.txt
├── comparison_report.txt
├── baseline_predictions.jsonl
├── finetuned_predictions.jsonl
├── failures.jsonl
├── metrics.json
├── experiment_config.json
├── checkpoints/
└── adapter/
```

`test.jsonl`은 최종 평가에만 사용하며 학습에 포함하지 않는다.

## 주의사항

- 학습에는 GGUF 양자화 모델이 아닌 Hugging Face 원본 모델을 사용한다.
- `SYSTEM_PROMPT`와 `DRONE_COMMAND_SCHEMA`는 현재 프로젝트 코드를 직접
  불러오므로 Prompt와 Schema 변경이 학습에 자동 반영된다.
- 발표용 본 실험에서는 `--skip-baseline-evaluation`을 사용하지 않는다.
- Vision 명령은 센서와 실행 함수가 구현되기 전까지 `unsupported`로 평가한다.
