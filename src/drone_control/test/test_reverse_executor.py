"""실행 완료 명령을 역방향 명령으로 변환하는 기능을 검증한다."""

from copy import deepcopy

import pytest

from drone_control.reverse_executor import ReverseExecutor


def make_move_command(
    direction: str,
    distance_m: float = 3.0,
    speed_mps: float | None = None,
) -> dict:
    """현재 Function Schema 형식의 이동 명령을 생성한다."""
    arguments = {
        "direction": direction,
        "distance_m": distance_m,
    }

    # speed_mps는 사용자가 속도를 지정한 경우에만 포함되는 선택 인자다.
    if speed_mps is not None:
        arguments["speed_mps"] = speed_mps

    return {
        "name": "move_drone",
        "arguments": arguments,
    }


def make_rotate_command(
    yaw_deg: float,
    yaw_speed_dps: float | None = None,
) -> dict:
    """현재 Function Schema 형식의 상대 회전 명령을 생성한다."""
    arguments = {
        "yaw_deg": yaw_deg,
    }

    # yaw_speed_dps도 Function Schema에서 선택 인자로 정의되어 있다.
    if yaw_speed_dps is not None:
        arguments["yaw_speed_dps"] = yaw_speed_dps

    return {
        "name": "rotate_relative",
        "arguments": arguments,
    }


@pytest.mark.parametrize(
    ("original_direction", "reverse_direction"),
    [
        ("forward", "backward"),
        ("backward", "forward"),
        ("left", "right"),
        ("right", "left"),
        ("up", "down"),
        ("down", "up"),
    ],
)
def test_reverse_move_direction(
    original_direction,
    reverse_direction,
):
    """모든 이동 방향이 서로 반대 방향으로 변환되는지 확인한다."""
    executor = ReverseExecutor()
    command = make_move_command(
        direction=original_direction,
        distance_m=3.0,
    )

    reversed_command = executor.reverse_action(command)

    assert reversed_command == {
        "name": "move_drone",
        "arguments": {
            "direction": reverse_direction,
            "distance_m": 3.0,
        },
    }


def test_reverse_move_preserves_distance_and_speed():
    """이동 방향 외의 거리와 속도 값은 그대로 유지해야 한다."""
    executor = ReverseExecutor()
    command = make_move_command(
        direction="forward",
        distance_m=5.0,
        speed_mps=1.5,
    )

    reversed_command = executor.reverse_action(command)

    assert reversed_command == {
        "name": "move_drone",
        "arguments": {
            "direction": "backward",
            "distance_m": 5.0,
            "speed_mps": 1.5,
        },
    }


@pytest.mark.parametrize(
    ("original_yaw_deg", "reverse_yaw_deg"),
    [
        (90.0, -90.0),
        (-45.0, 45.0),
    ],
)
def test_reverse_rotation_changes_yaw_sign(
    original_yaw_deg,
    reverse_yaw_deg,
):
    """
    상대 회전각의 부호가 반대로 변환되는지 확인한다.

    현재 Function Schema에서는 오른쪽 회전이 양수이고
    왼쪽 회전이 음수이다.
    """
    executor = ReverseExecutor()
    command = make_rotate_command(yaw_deg=original_yaw_deg)

    reversed_command = executor.reverse_action(command)

    assert reversed_command == {
        "name": "rotate_relative",
        "arguments": {
            "yaw_deg": reverse_yaw_deg,
        },
    }


def test_reverse_rotation_preserves_yaw_speed():
    """회전각의 부호만 바꾸고 회전 속도는 유지해야 한다."""
    executor = ReverseExecutor()
    command = make_rotate_command(
        yaw_deg=90.0,
        yaw_speed_dps=30.0,
    )

    reversed_command = executor.reverse_action(command)

    assert reversed_command == {
        "name": "rotate_relative",
        "arguments": {
            "yaw_deg": -90.0,
            "yaw_speed_dps": 30.0,
        },
    }


def test_build_reverse_plan_reverses_order_and_actions():
    """실행 기록의 순서와 각 명령의 방향을 모두 반대로 바꾼다."""
    executor = ReverseExecutor()
    actions = [
        make_move_command(direction="forward", distance_m=3.0),
        make_rotate_command(yaw_deg=90.0),
        make_move_command(direction="right", distance_m=2.0),
    ]

    reverse_plan = executor.build_reverse_plan(actions)

    # 마지막으로 실행했던 오른쪽 이동부터 반대로 실행해야
    # 원래 경로를 역순으로 따라갈 수 있다.
    assert reverse_plan == [
        make_move_command(direction="left", distance_m=2.0),
        make_rotate_command(yaw_deg=-90.0),
        make_move_command(direction="backward", distance_m=3.0),
    ]


def test_build_reverse_plan_accepts_empty_history():
    """실행 기록이 비어 있으면 빈 역추적 계획을 반환해야 한다."""
    executor = ReverseExecutor()

    assert executor.build_reverse_plan([]) == []


def test_reverse_executor_does_not_modify_original_actions():
    """역방향 계획을 생성해도 기존 Action History는 변하지 않아야 한다."""
    executor = ReverseExecutor()
    actions = [
        make_move_command(
            direction="forward",
            distance_m=3.0,
            speed_mps=1.0,
        ),
        make_rotate_command(
            yaw_deg=90.0,
            yaw_speed_dps=30.0,
        ),
    ]
    original_actions = deepcopy(actions)

    executor.build_reverse_plan(actions)

    assert actions == original_actions


def test_unsupported_action_is_rejected():
    """
    직접 역변환하도록 정의하지 않은 명령은 거부해야 한다.

    move_clock_direction은 FSM 또는 Control Layer가 실제 실행한
    move_drone과 rotate_relative 단위로 분해해 기록해야 한다.
    """
    executor = ReverseExecutor()
    unsupported_command = {
        "name": "move_clock_direction",
        "arguments": {
            "clock_hour": 3,
            "distance_m": 2.0,
            "face_direction": True,
        },
    }

    with pytest.raises(ValueError, match="move_clock_direction"):
        executor.reverse_action(unsupported_command)
