# 모델별 시뮬레이션 비교

`simulation_cases_example.jsonl`에는 30개 고정 문항이 있다. 두 모델에 **동일한 문항·순서**로 사용한다. 각 줄은 `case_id`, `category`, `input`, `expected_status`, `expected_commands`, `expected_runtime`을 포함한다. `expected_runtime`은 `execute` 또는 `reject`다. 정답 JSON은 스키마 검사를 통과하지만, 자연어 해석 정답은 실험 전에 팀이 다시 검토해야 한다.

문항을 한 번에 연속 실행하는 스크립트가 아니다. 이륙/이동/회전/호버링은 PX4 Offboard 및 기체 상태가 준비된 뒤, 같은 초기 위치·고도에서 각각 시작한다. `SIM-T11` 취소는 *진행 중인 이동·회전·시간 지정 호버링*이 있어야 성공한다. `SIM-T12`, `SIM-T30` 긴급 정지는 시뮬레이터에서만 시험하고, 각 실행 후 어댑터/기체 상태를 초기화한다. `SIM-T17` Recall은 먼저 이동 또는 회전 명령을 성공시켜 Action History를 만든 뒤 실행한다. `expected_runtime`이 `reject`인 문항에서는 드론이 움직이면 안 된다.

일부 문장은 기존 학습 데이터와 유사할 수 있으므로 이 30문항 결과를 독립적인 미지 데이터 성능으로 일반화하지 않는다. 발표에서는 **동일 조건의 두 모델에 대한 시뮬레이션 비교**로 표현한다.

빌드/환경 설정 후 실행 예시:

```bash
ros2 launch drone_llm llm_service.launch.py \
  model_id:=v0.4 \
  test_cases_file:=/home/hkit/ROS2-Gazebo-Drone-Sim/analysis/simulation_cases_example.jsonl
```

`model_sha256:=...`, `prompt_version:=...`도 지정할 수 있다. 모델 파일 경로는 기존 `qwen.yaml`에서 설정한다. v0.1과 v0.4를 바꿀 때 모델 이외의 프롬프트, 양자화 방식, 추론 설정, 시뮬레이터 초기 상태를 최대한 동일하게 유지한다. 첫 요청은 워밍업으로 별도 실행하고, 평가 명령은 하나가 끝난 뒤 다음을 입력한다.

결과는 `simulation_test_outputs/<시각>/run_manifest.json`과 `simulation_results.jsonl`에 저장된다. `px4_command` 필드는 기존 형식을 유지하지만 실제 PX4 `/fmu/in/*` 발행 확인이 아닌 `/drone/validated_command`의 브리지 발행 기록이다. `target_position`은 관측된 최신 궤적 setpoint이며, `position_error_m` 역시 그 setpoint 대비 값이다. 실제 기체 명령 수신·수행의 확증으로 해석하지 않는다.

두 실행 후:

```bash
python3 analysis/analyze_simulation_tests.py \
  simulation_test_outputs/<v0.1_실행폴더> \
  simulation_test_outputs/<v0.4_실행폴더> \
  --output-dir analysis/outputs/simulation_comparison
```

`case_scores.csv`는 문항별 명령/파라미터/전체 해석, 안전 거부 또는 실행, 단계별 지연, 위치 오차를 담는다. `model_summary.csv`는 채점 가능한 문항만 분모로 사용한 모델별 정확도와 중앙값을 담는다. `paired_comparison.csv`는 공통 `case_id`만 짝지어 개선·악화·양쪽 성공·양쪽 실패를 표시한다. 기대 정답이 없는 입력은 기록되지만 정확도 계산에서는 제외된다.

브리지의 단일 명령 제한 때문에 복합 명령이 거부될 수 있다. 그런 문항은 LLM 해석의 정확도와 런타임의 안전한 거부를 따로 읽어야 한다. `result=rejected`를 곧바로 모델 실패로 세지 않는다.
