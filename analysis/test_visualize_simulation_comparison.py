"""시뮬레이션 비교 시각화의 분류와 파일 생성을 검증한다."""

import csv
from pathlib import Path

from analysis.visualize_simulation_comparison import classify_case
from analysis.visualize_simulation_comparison import create_visualizations


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """테스트 입력용 CSV를 생성한다."""
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_classify_case_distinguishes_safe_rejection() -> None:
    """의도된 거부를 실행 성공 및 실패와 구분한다."""
    assert classify_case(
        {
            "interpretation_correct": "True",
            "runtime_correct": "True",
            "expected_runtime": "reject",
        }
    ) == "safe_rejection"
    assert classify_case(
        {
            "interpretation_correct": "False",
            "runtime_correct": "True",
            "expected_runtime": "execute",
        }
    ) == "interpretation_failure"


def test_create_visualizations_writes_expected_outputs(tmp_path: Path) -> None:
    """비교 CSV에서 모든 발표용 결과물이 생성된다."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "figures"
    input_dir.mkdir()
    case_rows = [
        {
            "model_id": "v0.1",
            "case_id": "SIM-T01",
            "natural_language_input": "2미터 이륙해",
            "expected_runtime": "execute",
            "llm_raw_response": '{"status":"invalid","commands":[]}',
            "interpretation_correct": False,
            "runtime_correct": False,
            "result": "rejected",
            "failure_reason": "명령 불일치",
            "llm_latency_seconds": 1.2,
            "elapsed_seconds": 1.5,
        },
        {
            "model_id": "v0.4",
            "case_id": "SIM-T01",
            "natural_language_input": "2미터 이륙해",
            "expected_runtime": "execute",
            "llm_raw_response": '{"status":"accepted","commands":[]}',
            "interpretation_correct": True,
            "runtime_correct": True,
            "result": "success",
            "failure_reason": "",
            "llm_latency_seconds": 0.8,
            "elapsed_seconds": 1.1,
        },
        {
            "model_id": "v0.1",
            "case_id": "SIM-T02",
            "natural_language_input": "복합 명령",
            "expected_runtime": "reject",
            "llm_raw_response": '{"status":"accepted","commands":[]}',
            "interpretation_correct": True,
            "runtime_correct": True,
            "result": "rejected",
            "failure_reason": "안전 거부",
            "llm_latency_seconds": 1.0,
            "elapsed_seconds": 1.3,
        },
        {
            "model_id": "v0.4",
            "case_id": "SIM-T02",
            "natural_language_input": "복합 명령",
            "expected_runtime": "reject",
            "llm_raw_response": '{"status":"accepted","commands":[]}',
            "interpretation_correct": True,
            "runtime_correct": True,
            "result": "rejected",
            "failure_reason": "안전 거부",
            "llm_latency_seconds": 0.7,
            "elapsed_seconds": 1.0,
        },
    ]
    summaries = [
        {
            "model_id": "v0.1",
            "test_count": 2,
            "command_correct_pct": 50,
            "parameter_correct_pct": 50,
            "end_to_end_correct_pct": 50,
        },
        {
            "model_id": "v0.4",
            "test_count": 2,
            "command_correct_pct": 100,
            "parameter_correct_pct": 100,
            "end_to_end_correct_pct": 100,
        },
    ]
    pairs = [
        {
            "case_id": "SIM-T01",
            "baseline": "v0.1",
            "candidate": "v0.4",
            "outcome": "improved",
        },
        {
            "case_id": "SIM-T02",
            "baseline": "v0.1",
            "candidate": "v0.4",
            "outcome": "both_correct",
        },
    ]
    write_csv(input_dir / "case_scores.csv", case_rows)
    write_csv(input_dir / "model_summary.csv", summaries)
    write_csv(input_dir / "paired_comparison.csv", pairs)

    outputs = create_visualizations(input_dir, output_dir)

    assert len(outputs) == 7
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs)
    representative = (output_dir / "representative_cases.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "SIM-T01" in representative
    assert "SIM-T02" not in representative
