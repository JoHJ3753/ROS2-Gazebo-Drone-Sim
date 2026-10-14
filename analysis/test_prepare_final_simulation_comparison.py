"""최종 시뮬레이션 로그 정규화 규칙을 검증한다."""

from analysis.prepare_final_simulation_comparison import CASES
from analysis.prepare_final_simulation_comparison import normalize_records


def test_normalize_records_assigns_unique_case_ids() -> None:
    """반복 이륙 문항도 실행 목적에 따라 고유 ID를 가진다."""
    records = [
        {"natural_language_input": case.input_text}
        for case in CASES
    ]
    normalized = normalize_records(records, "test-model")
    case_ids = [record["case_id"] for record in normalized]
    assert len(case_ids) == len(set(case_ids))
    assert normalized[-1]["case_id"] == "EMERGENCY-02-STOP"


def test_normalize_records_rejects_different_order() -> None:
    """문항 순서가 달라지면 잘못된 모델 비교 생성을 차단한다."""
    records = [
        {"natural_language_input": case.input_text}
        for case in CASES
    ]
    records[0]["natural_language_input"] = "다른 문항"
    try:
        normalize_records(records, "test-model")
    except ValueError as error:
        assert "문항 불일치" in str(error)
    else:
        raise AssertionError("문항 불일치를 감지하지 못했습니다.")
