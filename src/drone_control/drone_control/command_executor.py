"""검증된 드론 명령 한 개를 대응하는 비행 함수로 전달한다."""

import math
from numbers import Real
from typing import Any, Protocol

from drone_control.action_history import Command


class CommandExecutionError(ValueError):
    """명령 구조나 인자가 실행기에 맞지 않을 때 발생한다."""


class DroneCommandHandler(Protocol):
    """CommandExecutor가 호출할 비행 제어 함수의 인터페이스다."""

    def arm(self) -> None:
        """드론을 시동한다."""

    def disarm(self) -> None:
        """드론의 시동을 해제한다."""

    def takeoff(self, altitude_m: float) -> None:
        """지정한 고도로 이륙한다."""

    def land(self) -> None:
        """현재 위치에서 착륙한다."""

    def move_drone(
        self,
        direction: str,
        distance_m: float,
        speed_mps: float | None,
    ) -> None:
        """현재 기수를 기준으로 지정한 방향과 거리만큼 이동한다."""

    def rotate_relative(
        self,
        yaw_deg: float,
        yaw_speed_dps: float | None,
    ) -> None:
        """현재 기수를 기준으로 지정한 각도만큼 회전한다."""

    def hover(self, duration_s: float | None) -> None:
        """현재 위치와 기수를 유지한다."""


_SUPPORTED_COMMAND_NAMES = frozenset(
    {
        "arm",
        "disarm",
        "takeoff",
        "land",
        "move_drone",
        "rotate_relative",
        "hover",
    }
)

_MOVE_DIRECTIONS = frozenset(
    {
        "forward",
        "backward",
        "left",
        "right",
        "up",
        "down",
    }
)


class CommandExecutor:
    """검증된 명령을 주입받은 비행 제어 함수로 전달한다."""

    def __init__(self, handler: DroneCommandHandler) -> None:
        """실제 비행 명령을 받을 handler를 저장한다."""
        self._handler = handler

    def execute(self, command: Command) -> None:
        """하나의 명령을 검증한 뒤 대응하는 handler 함수를 호출한다."""
        command_name, arguments = self._validate_command(command)

        if command_name == "arm":
            self._require_arguments(arguments, required=set(), optional=set())
            self._handler.arm()
            return

        if command_name == "disarm":
            self._require_arguments(arguments, required=set(), optional=set())
            self._handler.disarm()
            return

        if command_name == "takeoff":
            self._execute_takeoff(arguments)
            return

        if command_name == "land":
            self._require_arguments(arguments, required=set(), optional=set())
            self._handler.land()
            return

        if command_name == "move_drone":
            self._execute_move_drone(arguments)
            return

        if command_name == "rotate_relative":
            self._execute_rotate_relative(arguments)
            return

        if command_name == "hover":
            self._execute_hover(arguments)
            return

        # _validate_command에서 지원 여부를 확인하므로 도달할 수 없다.
        raise CommandExecutionError(
            f"Unsupported command: {command_name}"
        )

    def _execute_takeoff(self, arguments: dict[str, Any]) -> None:
        """이륙 인자를 검증하고 handler에 전달한다."""
        self._require_arguments(
            arguments,
            required={"altitude_m"},
            optional=set(),
        )
        altitude_m = self._require_positive_number(
            arguments["altitude_m"],
            name="altitude_m",
        )
        self._handler.takeoff(altitude_m)

    def _execute_move_drone(self, arguments: dict[str, Any]) -> None:
        """상대이동 인자를 검증하고 handler에 전달한다."""
        self._require_arguments(
            arguments,
            required={"direction", "distance_m"},
            optional={"speed_mps"},
        )

        direction = arguments["direction"]
        if not isinstance(direction, str) or direction not in _MOVE_DIRECTIONS:
            raise CommandExecutionError(
                f"Unsupported move direction: {direction!r}"
            )

        distance_m = self._require_positive_number(
            arguments["distance_m"],
            name="distance_m",
        )
        speed_mps = self._optional_positive_number(
            arguments,
            name="speed_mps",
        )
        self._handler.move_drone(
            direction,
            distance_m,
            speed_mps,
        )

    def _execute_rotate_relative(
        self,
        arguments: dict[str, Any],
    ) -> None:
        """상대회전 인자를 검증하고 handler에 전달한다."""
        self._require_arguments(
            arguments,
            required={"yaw_deg"},
            optional={"yaw_speed_dps"},
        )
        yaw_deg = self._require_finite_number(
            arguments["yaw_deg"],
            name="yaw_deg",
        )
        yaw_speed_dps = self._optional_positive_number(
            arguments,
            name="yaw_speed_dps",
        )
        self._handler.rotate_relative(
            yaw_deg,
            yaw_speed_dps,
        )

    def _execute_hover(self, arguments: dict[str, Any]) -> None:
        """호버링 인자를 검증하고 handler에 전달한다."""
        self._require_arguments(
            arguments,
            required=set(),
            optional={"duration_s"},
        )
        duration_s = self._optional_positive_number(
            arguments,
            name="duration_s",
        )
        self._handler.hover(duration_s)

    @staticmethod
    def _validate_command(
        command: Command,
    ) -> tuple[str, dict[str, Any]]:
        """명령의 공통 구조와 지원 여부를 확인한다."""
        if not isinstance(command, dict):
            raise CommandExecutionError("Command must be a dictionary")

        command_keys = set(command)
        expected_keys = {"name", "arguments"}
        if command_keys != expected_keys:
            raise CommandExecutionError(
                "Command must contain only name and arguments"
            )

        command_name = command["name"]
        if not isinstance(command_name, str):
            raise CommandExecutionError("Command name must be a string")

        if command_name not in _SUPPORTED_COMMAND_NAMES:
            raise CommandExecutionError(
                f"Unsupported command: {command_name}"
            )

        arguments = command["arguments"]
        if not isinstance(arguments, dict):
            raise CommandExecutionError(
                "Command arguments must be a dictionary"
            )

        return command_name, arguments

    @staticmethod
    def _require_arguments(
        arguments: dict[str, Any],
        required: set[str],
        optional: set[str],
    ) -> None:
        """필수 인자 누락과 허용되지 않은 인자를 검사한다."""
        argument_names = set(arguments)
        missing = required - argument_names
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise CommandExecutionError(
                f"Missing command arguments: {missing_names}"
            )

        unexpected = argument_names - required - optional
        if unexpected:
            unexpected_names = ", ".join(sorted(unexpected))
            raise CommandExecutionError(
                f"Unexpected command arguments: {unexpected_names}"
            )

    @staticmethod
    def _require_finite_number(value: Any, name: str) -> float:
        """불리언이 아닌 유한한 실수를 반환한다."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise CommandExecutionError(
                f"{name} must be a finite number"
            )

        converted_value = float(value)
        if not math.isfinite(converted_value):
            raise CommandExecutionError(
                f"{name} must be a finite number"
            )

        return converted_value

    @classmethod
    def _require_positive_number(cls, value: Any, name: str) -> float:
        """0보다 큰 유한한 실수를 반환한다."""
        converted_value = cls._require_finite_number(value, name)
        if converted_value <= 0.0:
            raise CommandExecutionError(
                f"{name} must be greater than zero"
            )

        return converted_value

    @classmethod
    def _optional_positive_number(
        cls,
        arguments: dict[str, Any],
        name: str,
    ) -> float | None:
        """선택 인자가 있으면 양수로 검증하고, 없으면 None을 반환한다."""
        if name not in arguments:
            return None

        return cls._require_positive_number(arguments[name], name)
