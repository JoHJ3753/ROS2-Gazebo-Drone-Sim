"""LLM 응답에서 현재 실행 가능한 단일 드론 명령을 추출한다."""

from typing import Any

from drone_command_interface.command_output_parser import (
    parse_command_output,
)


SUPPORTED_RUNTIME_COMMANDS = frozenset(
    {
        "arm",
        "takeoff",
        "land",
        "move_drone",
        "rotate_relative",
        "hover",
        "cancel",
        "emergency_stop",
        "return_home",
    }
)
MAX_UNAMBIGUOUS_YAW_DEG = 180.0


class CommandBridgeError(ValueError):
    """LLM 응답을 현재 PX4 런타임에 전달할 수 없을 때 발생한다."""


def prepare_runtime_command(raw_response: str) -> dict[str, Any]:
    """스키마를 검증하고 현재 지원하는 단일 명령만 반환한다."""
    result = parse_command_output(raw_response)

    if result["status"] != "accepted":
        raise CommandBridgeError(result["message"])

    commands = result["commands"]
    if len(commands) != 1:
        raise CommandBridgeError(
            "명령 완료 확인 기능이 없어 복합 명령은 실행하지 않습니다."
        )

    command = commands[0]
    if command["name"] not in SUPPORTED_RUNTIME_COMMANDS:
        raise CommandBridgeError(
            f"현재 실행할 수 없는 명령입니다: {command['name']}"
        )

    if (
        command["name"] == "move_drone"
        and "speed_mps" in command["arguments"]
    ):
        raise CommandBridgeError(
            "이동 속도(speed_mps) 지정은 아직 지원하지 않습니다."
        )

    if command["name"] == "rotate_relative":
        arguments = command["arguments"]
        if "yaw_speed_dps" in arguments:
            raise CommandBridgeError(
                "회전 속도(yaw_speed_dps) 지정은 아직 지원하지 않습니다."
            )

        # PX4 목표 yaw는 정규화되므로 큰 각도는 요청한 회전 경로를
        # 보장하지 못한다. 360도는 제자리 완료로 판정될 수도 있다.
        if abs(arguments["yaw_deg"]) >= MAX_UNAMBIGUOUS_YAW_DEG:
            raise CommandBridgeError(
                "180도 이상 회전은 현재 제어 방식으로 보장할 수 없습니다."
            )

    return command
