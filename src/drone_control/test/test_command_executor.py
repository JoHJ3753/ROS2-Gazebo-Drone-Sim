"""CommandExecutor 단위 테스트."""

from typing import Any

import pytest

from drone_control.command_executor import CommandExecutionError
from drone_control.command_executor import CommandExecutor


class FakeDroneCommandHandler:
    """실제 비행 없이 호출 내역만 저장하는 테스트용 handler다."""

    def __init__(self) -> None:
        """빈 호출 기록을 생성한다."""
        self.calls: list[tuple[Any, ...]] = []

    def arm(self) -> None:
        """시동 호출을 기록한다."""
        self.calls.append(("arm",))

    def disarm(self) -> None:
        """시동 해제 호출을 기록한다."""
        self.calls.append(("disarm",))

    def takeoff(self, altitude_m: float) -> None:
        """이륙 호출을 기록한다."""
        self.calls.append(("takeoff", altitude_m))

    def land(self) -> None:
        """착륙 호출을 기록한다."""
        self.calls.append(("land",))

    def return_home(self) -> None:
        """홈 복귀 호출을 기록한다."""
        self.calls.append(("return_home",))

    def move_drone(
        self,
        direction: str,
        distance_m: float,
        speed_mps: float | None,
    ) -> None:
        """상대이동 호출을 기록한다."""
        self.calls.append(
            ("move_drone", direction, distance_m, speed_mps)
        )

    def rotate_relative(
        self,
        yaw_deg: float,
        yaw_speed_dps: float | None,
    ) -> None:
        """상대회전 호출을 기록한다."""
        self.calls.append(
            ("rotate_relative", yaw_deg, yaw_speed_dps)
        )

    def hover(self, duration_s: float | None) -> None:
        """호버링 호출을 기록한다."""
        self.calls.append(("hover", duration_s))

    def cancel(self) -> None:
        """비행 동작 취소 호출을 기록한다."""
        self.calls.append(("cancel",))

    def emergency_stop(self) -> None:
        """긴급 정지 호출을 기록한다."""
        self.calls.append(("emergency_stop",))


@pytest.mark.parametrize(
    "command, expected_call",
    [
        ({"name": "arm", "arguments": {}}, ("arm",)),
        ({"name": "disarm", "arguments": {}}, ("disarm",)),
        (
            {"name": "takeoff", "arguments": {"altitude_m": 2}},
            ("takeoff", 2.0),
        ),
        ({"name": "land", "arguments": {}}, ("land",)),
        (
            {"name": "return_home", "arguments": {}},
            ("return_home",),
        ),
        (
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",
                    "distance_m": 1.5,
                },
            },
            ("move_drone", "forward", 1.5, None),
        ),
        (
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "left",
                    "distance_m": 2.0,
                    "speed_mps": 0.5,
                },
            },
            ("move_drone", "left", 2.0, 0.5),
        ),
        (
            {
                "name": "rotate_relative",
                "arguments": {"yaw_deg": -90},
            },
            ("rotate_relative", -90.0, None),
        ),
        (
            {
                "name": "rotate_relative",
                "arguments": {
                    "yaw_deg": 90.0,
                    "yaw_speed_dps": 30.0,
                },
            },
            ("rotate_relative", 90.0, 30.0),
        ),
        ({"name": "hover", "arguments": {}}, ("hover", None)),
        (
            {"name": "hover", "arguments": {"duration_s": 3.0}},
            ("hover", 3.0),
        ),
        ({"name": "cancel", "arguments": {}}, ("cancel",)),
        (
            {"name": "emergency_stop", "arguments": {}},
            ("emergency_stop",),
        ),
    ],
)
def test_execute_routes_valid_command(
    command: dict[str, Any],
    expected_call: tuple[Any, ...],
) -> None:
    """지원하는 명령을 정확한 handler 함수와 인자로 전달한다."""
    handler = FakeDroneCommandHandler()
    executor = CommandExecutor(handler)

    executor.execute(command)

    assert handler.calls == [expected_call]


@pytest.mark.parametrize(
    "command",
    [
        None,
        [],
        {},
        {"name": "arm"},
        {"name": "arm", "arguments": {}, "extra": True},
        {"name": 1, "arguments": {}},
        {"name": "arm", "arguments": []},
    ],
)
def test_execute_rejects_invalid_command_structure(command: Any) -> None:
    """잘못된 공통 구조나 아직 지원하지 않는 명령을 거부한다."""
    handler = FakeDroneCommandHandler()
    executor = CommandExecutor(handler)

    with pytest.raises(CommandExecutionError):
        executor.execute(command)

    assert handler.calls == []


@pytest.mark.parametrize(
    "command",
    [
        {"name": "arm", "arguments": {"unexpected": 1}},
        {"name": "takeoff", "arguments": {}},
        {
            "name": "takeoff",
            "arguments": {"altitude_m": 2.0, "unexpected": 1},
        },
        {
            "name": "move_drone",
            "arguments": {"direction": "forward"},
        },
        {
            "name": "rotate_relative",
            "arguments": {},
        },
        {
            "name": "hover",
            "arguments": {"unexpected": 1},
        },
        {"name": "cancel", "arguments": {"unexpected": 1}},
        {
            "name": "return_home",
            "arguments": {"unexpected": 1},
        },
        {
            "name": "emergency_stop",
            "arguments": {"unexpected": 1},
        },
    ],
)
def test_execute_rejects_missing_or_unexpected_arguments(
    command: dict[str, Any],
) -> None:
    """필수 인자가 없거나 정의되지 않은 인자가 있으면 거부한다."""
    handler = FakeDroneCommandHandler()
    executor = CommandExecutor(handler)

    with pytest.raises(CommandExecutionError):
        executor.execute(command)

    assert handler.calls == []


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("takeoff", {"altitude_m": True}),
        ("takeoff", {"altitude_m": 0}),
        ("takeoff", {"altitude_m": float("nan")}),
        (
            "move_drone",
            {"direction": "forward", "distance_m": -1},
        ),
        (
            "move_drone",
            {
                "direction": "forward",
                "distance_m": 1,
                "speed_mps": float("inf"),
            },
        ),
        ("rotate_relative", {"yaw_deg": False}),
        ("rotate_relative", {"yaw_deg": float("inf")}),
        (
            "rotate_relative",
            {"yaw_deg": 90, "yaw_speed_dps": 0},
        ),
        ("hover", {"duration_s": -1}),
    ],
)
def test_execute_rejects_invalid_numeric_arguments(
    name: str,
    arguments: dict[str, Any],
) -> None:
    """불리언, 비유한 숫자 또는 허용 범위를 벗어난 숫자를 거부한다."""
    handler = FakeDroneCommandHandler()
    executor = CommandExecutor(handler)

    with pytest.raises(CommandExecutionError):
        executor.execute({"name": name, "arguments": arguments})

    assert handler.calls == []


@pytest.mark.parametrize(
    "direction",
    [None, 1, "north", "FORWARD", ""],
)
def test_execute_rejects_unsupported_move_direction(direction: Any) -> None:
    """스키마에 없는 이동 방향을 거부한다."""
    handler = FakeDroneCommandHandler()
    executor = CommandExecutor(handler)
    command = {
        "name": "move_drone",
        "arguments": {
            "direction": direction,
            "distance_m": 1.0,
        },
    }

    with pytest.raises(CommandExecutionError):
        executor.execute(command)

    assert handler.calls == []
