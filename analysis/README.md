# 파인튜닝 결과 분석

`test_result/test_result_v*` 폴더를 자동으로 찾아 버전별 평가 지표,
명령별 정확도, 실패 유형, 학습 Loss를 CSV와 PNG로 변환한다.

## 실행

프로젝트 최상위 폴더에서 실행한다.

```bash
python3 analysis/analyze_results.py
```

결과는 `analysis/outputs`에 생성된다.

```text
analysis/outputs/
├── csv/
├── figures/
└── reports/
```

`csv/version_summary.csv`에는 발표 자료에서 바로 사용할 버전별 핵심
정확도와 학습 조건이 한 행으로 정리된다. `analysis_summary.txt`는 수치가
아닌 결과 해석과 비교 시 주의사항을 보존한다.

`csv/experiment_metadata.csv`에는 버전별 데이터 개수, epoch, 학습률,
초기 어댑터, 최종 Train/Eval Loss가 기록된다. 이어 학습한 버전의
baseline은 원본 모델이 아니라 초기 어댑터의 성능으로 해석한다.

주요 발표용 그래프는 다음과 같이 생성된다.

- `overall_accuracy.png`: 동일 시험셋과 별도 시험셋을 분리한 정확도 비교
- `improvement_comparison.png`: 파인튜닝 전후 덤벨 차트
- `command_accuracy.png`: 명령별 정확도와 표본 수 히트맵
- `failure_distribution.png`: 성공 및 실패 원인의 100% 누적 막대그래프
- `training_loss.png`: 원본 Loss와 5-step 이동평균 추세
- `eval_loss.png`: 버전별 최종 Validation Loss
- `eval_loss_by_epoch.png`: 다중 epoch 버전의 epoch별 Loss 변화

v0.6 학습 결과를 다음과 같이 추가한 뒤 같은 명령을 다시 실행하면
기존 CSV와 그래프에 새 버전이 자동으로 반영된다.

```text
test_result/test_result_v0.6_base/
test_result/test_result_v0.6_continued/
```

각 결과 폴더에는 최소한 다음 파일이 있어야 한다.

```text
metrics.json
baseline_predictions.jsonl
finetuned_predictions.jsonl
```

학습 곡선을 포함하려면 `training_log` 또는 `training_log.txt`도 필요하다.

## 비교 기준

- 시험 입력과 정답이 같은 결과끼리만 직접 비교한다.
- CSV의 `benchmark_id`가 같으면 동일 시험셋이다.
- v0.1~v0.4는 동일 시험셋이고 v0.5는 별도 시험셋이다.
- 명령별 정확도는 기대 명령이 있는 샘플만 집계한다.
- 복합 명령은 포함된 각 명령의 통계에 귀속된다.
