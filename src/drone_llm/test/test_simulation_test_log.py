"""시뮬레이션 테스트 로그의 순수 Python 로직을 검증한다."""

import json
from datetime import datetime

from drone_llm.simulation_test_log import JsonlTestWriter
from drone_llm.simulation_test_log import PositionSnapshot
from drone_llm.simulation_test_log import SimulationTestRecord
from drone_llm.simulation_test_log import classify_bridge_failure
from drone_llm.simulation_test_log import is_failure_status
from drone_llm.simulation_test_log import is_success_status
from drone_llm.simulation_test_log import make_run_directory


def test_jsonl_writer_saves_nested_record(tmp_path) -> None:
    """좌표와 명령을 포함한 기록을 JSONL 한 줄로 저장한다."""
    writer = JsonlTestWriter(tmp_path)
    record = SimulationTestRecord(
        timestamp="2026-09-21T17:00:00+09:00",
        test_id="SIM-0001",
        natural_language_input="2미터 이륙해",
        parsed_command={
            "name": "takeoff",
            "arguments": {"altitude_m": 2.0},
        },
        initial_position=PositionSnapshot(
            x=0.0,
            y=0.0,
            z=0.0,
            yaw_rad=0.0,
        ),
        result="success",
    )

    writer.append(record)

    saved = json.loads(writer.output_path.read_text(encoding="utf-8"))
    assert saved["test_id"] == "SIM-0001"
    assert saved["parsed_command"]["name"] == "takeoff"
    assert saved["initial_position"]["z"] == 0.0


def test_run_directory_uses_suffix_when_timestamp_exists(tmp_path) -> None:
    """같은 초에 재실행해도 기존 결과 폴더를 덮어쓰지 않는다."""
    started_at = datetime(2026, 9, 21, 17, 0, 0)
    first_directory = make_run_directory(tmp_path, started_at)
    first_directory.mkdir()

    second_directory = make_run_directory(tmp_path, started_at)

    assert second_directory.name == "2026-09-21_170000_01"


def test_bridge_failure_classification() -> None:
    """대표적인 브리지 거부 원인을 실패 단계로 구분한다."""
    assert classify_bridge_failure(
        "거부됨: LLM 서비스가 준비되지 않았습니다."
    )[0] == "llm"
    assert classify_bridge_failure(
        "거부됨: PX4 어댑터가 연결되지 않았습니다."
    )[0] == "bridge"
    assert classify_bridge_failure(
        "거부됨: 현재 실행할 수 없는 명령입니다."
    )[0] == "schema_validation"


def test_flight_status_classification() -> None:
    """완료와 실패 상태만 테스트 종료 조건으로 인식한다."""
    assert is_success_status("목표 위치 도달: 호버링 중")
    assert is_success_status("착륙 완료: 시동 해제 확인")
    assert is_failure_status("비행 오류: PX4 position is stale")
    assert not is_success_status("이동 중: 목표 위치로 비행")
