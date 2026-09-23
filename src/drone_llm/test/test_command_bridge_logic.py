"""LLM 응답의 런타임 명령 선별을 검증한다."""

import json

import pytest

from drone_command_interface.command_output_parser import (
    InvalidModelOutputError,
)
from drone_llm.command_bridge_logic import CommandBridgeError
from drone_llm.command_bridge_logic import prepare_runtime_command


def make_response(commands: list[dict]) -> str:
    """정상 형식의 accepted 응답을 생성한다."""
    return json.dumps(
        {"status": "accepted", "commands": commands, "message": None}
    )


def test_single_arm_is_accepted() -> None:
    """실행 가능한 단일 시동 명령을 전달한다."""
    command = {"name": "arm", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_takeoff_is_accepted() -> None:
    """실행 가능한 단일 이륙 명령을 전달한다."""
    command = {"name": "takeoff", "arguments": {"altitude_m": 2.0}}

    assert prepare_runtime_command(make_response([command])) == command


def test_malformed_output_is_rejected() -> None:
    """스키마에 맞지 않는 LLM 출력은 전달하지 않는다."""
    with pytest.raises(InvalidModelOutputError):
        prepare_runtime_command("not json")


def test_clarification_is_not_executed() -> None:
    """재질문 상태에서는 명령을 실행하지 않는다."""
    response = json.dumps(
        {
            "status": "clarification_required",
            "commands": [],
            "message": "고도를 알려주세요.",
        }
    )

    with pytest.raises(CommandBridgeError, match="고도를 알려주세요"):
        prepare_runtime_command(response)


def test_single_land_is_accepted() -> None:
    """실행 가능한 단일 착륙 명령을 전달한다."""
    command = {"name": "land", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_move_without_speed_is_accepted() -> None:
    """방향과 거리만 있는 단일 상대이동을 전달한다."""
    command = {
        "name": "move_drone",
        "arguments": {"direction": "forward", "distance_m": 1.0},
    }

    assert prepare_runtime_command(make_response([command])) == command


def test_move_with_speed_is_rejected() -> None:
    """속도 제어가 구현되기 전에는 명시된 속도를 무시하지 않는다."""
    command = {
        "name": "move_drone",
        "arguments": {
            "direction": "forward",
            "distance_m": 1.0,
            "speed_mps": 0.5,
        },
    }

    with pytest.raises(CommandBridgeError, match="speed_mps"):
        prepare_runtime_command(make_response([command]))


def test_single_rotation_without_speed_is_accepted() -> None:
    """회전각만 있는 단일 상대회전을 전달한다."""
    command = {
        "name": "rotate_relative",
        "arguments": {"yaw_deg": 90.0},
    }

    assert prepare_runtime_command(make_response([command])) == command


def test_rotation_with_speed_is_rejected() -> None:
    """미구현 회전 속도는 무시하지 않고 거부한다."""
    command = {
        "name": "rotate_relative",
        "arguments": {"yaw_deg": 90.0, "yaw_speed_dps": 30.0},
    }

    with pytest.raises(CommandBridgeError, match="yaw_speed_dps"):
        prepare_runtime_command(make_response([command]))


@pytest.mark.parametrize("yaw_deg", [180.0, 270.0, 360.0, -360.0])
def test_rotation_without_guaranteed_path_is_rejected(
    yaw_deg: float,
) -> None:
    """정규화 때문에 요청한 회전 경로가 보장되지 않으면 거부한다."""
    command = {
        "name": "rotate_relative",
        "arguments": {"yaw_deg": yaw_deg},
    }

    with pytest.raises(CommandBridgeError, match="180도 이상"):
        prepare_runtime_command(make_response([command]))


def test_single_hover_without_duration_is_accepted() -> None:
    """시간이 없는 단일 호버링 명령을 전달한다."""
    command = {"name": "hover", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_timed_hover_is_accepted() -> None:
    """시간이 지정된 단일 호버링 명령을 전달한다."""
    command = {"name": "hover", "arguments": {"duration_s": 3.0}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_cancel_is_accepted() -> None:
    """실행 가능한 단일 취소 명령을 전달한다."""
    command = {"name": "cancel", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_emergency_stop_is_accepted() -> None:
    """실행 가능한 단일 긴급 정지 명령을 전달한다."""
    command = {"name": "emergency_stop", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_return_home_is_accepted() -> None:
    """실행 가능한 단일 홈 복귀 명령을 전달한다."""
    command = {"name": "return_home", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_single_recall_is_accepted() -> None:
    """실행 가능한 단일 경로 역추적 명령을 전달한다."""
    command = {"name": "recall", "arguments": {}}

    assert prepare_runtime_command(make_response([command])) == command


def test_compound_command_is_rejected() -> None:
    """완료 확인 없이 연속 명령을 발행하지 않는다."""
    takeoff = {"name": "takeoff", "arguments": {"altitude_m": 2.0}}
    land = {"name": "land", "arguments": {}}

    with pytest.raises(CommandBridgeError, match="복합 명령"):
        prepare_runtime_command(make_response([takeoff, land]))
