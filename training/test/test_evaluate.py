"""학습 평가 보고서 생성 기능을 검증한다."""

from pathlib import Path
from typing import Any

from training.evaluate import calculate_metrics
from training.evaluate import write_comparison_report


def _successful_record() -> dict[str, Any]:
    """모든 평가 항목에 성공한 착륙 기록을 반환한다."""
    return {
        "sample_index": 1,
        "category": "basic_single",
        "input": "착륙혀",
        "expected": {
            "status": "accepted",
            "commands": [
                {"name": "land", "arguments": {}},
            ],
            "message": None,
        },
        "prediction_raw": (
            '{"status":"accepted","commands":'
            '[{"name":"land","arguments":{}}],"message":null}'
        ),
        "metrics": {
            "json_parse": True,
            "schema_valid": True,
            "status_match": True,
            "command_match": True,
            "parameter_match": True,
            "exact_match": True,
            "hanja_free": True,
        },
    }


def test_comparison_report_contains_robustness_metrics(
    tmp_path: Path,
) -> None:
    """오타·사투리의 명령 및 파라미터 정확도를 보고서에 기록한다."""
    record = _successful_record()
    metrics = calculate_metrics([record])
    report_path = tmp_path / "comparison_report.txt"

    write_comparison_report(
        path=report_path,
        experiment_info={"Dataset": "dataset_v0.6"},
        baseline_records=[record],
        baseline_metrics=metrics,
        fine_tuned_records=[record],
        fine_tuned_metrics=metrics,
        robustness_baseline_records=[record],
        robustness_baseline_metrics=metrics,
        robustness_fine_tuned_records=[record],
        robustness_fine_tuned_metrics=metrics,
    )

    report = report_path.read_text(encoding="utf-8")
    assert "[오타·사투리 강건성 성능]" in report
    assert "명령 이름·순서 정확도" in report
    assert "파라미터 정확도" in report


def test_comparison_report_omits_robustness_without_records(
    tmp_path: Path,
) -> None:
    """강건성 평가 파일이 없으면 기존 보고서 형식을 유지한다."""
    record = _successful_record()
    metrics = calculate_metrics([record])
    report_path = tmp_path / "comparison_report.txt"

    write_comparison_report(
        path=report_path,
        experiment_info={"Dataset": "dataset_v0.5"},
        baseline_records=[record],
        baseline_metrics=metrics,
        fine_tuned_records=[record],
        fine_tuned_metrics=metrics,
    )

    report = report_path.read_text(encoding="utf-8")
    assert "[전체 성능]" in report
    assert "[오타·사투리 강건성 성능]" not in report
