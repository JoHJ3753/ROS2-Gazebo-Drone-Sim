"""시뮬레이션 비교 지표의 채점 규칙을 확인한다."""

from analysis.analyze_simulation_tests import compare_pairs
from analysis.analyze_simulation_tests import score_record
from analysis.analyze_simulation_tests import summarize


def test_correct_safe_rejection_is_scored_separately() -> None:
    """안전한 거부를 실행 실패로 단정하지 않는다."""
    record = {
        "model_id": "v0.4",
        "case_id": "T01",
        "llm_raw_response": '{"status":"unsupported","commands":[]}',
        "expected_status": "unsupported",
        "expected_commands": [],
        "expected_runtime": "reject",
        "result": "rejected",
        "px4_command": None,
    }
    score = score_record(record)
    assert score["interpretation_correct"] is True
    assert score["runtime_correct"] is True
    assert score["end_to_end_correct"] is True


def test_pairwise_comparison_detects_improvement() -> None:
    """같은 문항의 실패에서 성공으로 바뀐 경우만 개선으로 센다."""
    rows = [
        {"model_id": "v0.1", "case_id": "T01", "end_to_end_correct": False},
        {"model_id": "v0.4", "case_id": "T01", "end_to_end_correct": True},
    ]
    assert compare_pairs(rows, "v0.1", "v0.4")[0]["outcome"] == "improved"


def test_summary_excludes_unscored_cases() -> None:
    """정답 미지정 문항이 정확도 분모에 들어가지 않는다."""
    rows = [
        {
            "model_id": "v0.4", "interpretation_correct": True,
            "runtime_correct": True, "end_to_end_correct": True,
            "llm_latency_seconds": 1.0, "elapsed_seconds": 2.0,
            "position_error_m": None,
        },
        {
            "model_id": "v0.4", "interpretation_correct": None,
            "runtime_correct": None, "end_to_end_correct": None,
            "llm_latency_seconds": None, "elapsed_seconds": None,
            "position_error_m": None,
        },
    ]
    assert summarize(rows)[0]["end_to_end_correct_pct"] == 100.0
