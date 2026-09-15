"""자연어 드론 명령을 구조화된 명령 목록으로 변환하기 위한 스키마와 프롬프트."""

from typing import Any


def _command(
    name: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """공통 명령 객체 스키마를 생성한다."""
    arguments: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties or {},
    }

    if required:
        arguments["required"] = required

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"const": name},
            "arguments": arguments,
        },
        "required": ["name", "arguments"],
    }


# ============================================================
# 개별 드론 명령 스키마
# ============================================================

ARM_COMMAND = _command("arm")

DISARM_COMMAND = _command("disarm")

TAKEOFF_COMMAND = _command(
    "takeoff",
    properties={
        "altitude_m": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "이륙 후 도달할 지면 기준 목표 고도(m)",
        },
    },
    required=["altitude_m"],
)

LAND_COMMAND = _command("land")

MOVE_RELATIVE_COMMAND = _command(
    "move_relative",
    properties={
        "forward_m": {
            "type": "number",
            "description": "현재 기수 기준 전후 이동 거리(m). 전진은 양수, 후진은 음수",
        },
        "right_m": {
            "type": "number",
            "description": "현재 기수 기준 좌우 이동 거리(m). 오른쪽은 양수, 왼쪽은 음수",
        },
        "up_m": {
            "type": "number",
            "description": "현재 위치 기준 수직 이동 거리(m). 상승은 양수, 하강은 음수",
        },
        "speed_mps": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "사용자가 명시한 이동 속도(m/s). 지정하지 않은 경우 생략",
        },
    },
    required=[
        "forward_m",
        "right_m",
        "up_m",
    ],
)

MOVE_CLOCK_DIRECTION_COMMAND = _command(
    "move_clock_direction",
    properties={
        "clock_hour": {
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "description": (
                "현재 기수 기준 시계 방향. "
                "12시는 정면, 3시는 오른쪽, 6시는 뒤, 9시는 왼쪽"
            ),
        },
        "distance_m": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "해당 시계 방향으로 이동할 거리(m)",
        },
        "face_direction": {
            "type": "boolean",
            "description": (
                "이동 전에 해당 방향으로 기수를 회전하면 true, "
                "현재 기수를 유지한 채 이동하면 false"
            ),
        },
        "speed_mps": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "사용자가 명시한 이동 속도(m/s). 지정하지 않은 경우 생략",
        },
    },
    required=[
        "clock_hour",
        "distance_m",
        "face_direction",
    ],
)

ROTATE_RELATIVE_COMMAND = _command(
    "rotate_relative",
    properties={
        "yaw_deg": {
            "type": "number",
            "description": "현재 기수 기준 상대 회전각(degree). 오른쪽은 양수, 왼쪽은 음수",
        },
        "yaw_speed_dps": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "사용자가 명시한 회전 속도(degree/s). 지정하지 않은 경우 생략",
        },
    },
    required=["yaw_deg"],
)

HOVER_COMMAND = _command(
    "hover",
    properties={
        "duration_s": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "호버링 시간(s). 사용자가 시간을 지정하지 않은 경우 생략",
        },
    },
)

TAKE_PHOTO_COMMAND = _command(
    "take_photo",
    properties={
        "count": {
            "type": "integer",
            "minimum": 1,
            "description": "촬영할 사진 수. 사용자가 생략한 경우 1",
        },
        "interval_s": {
            "type": "number",
            "minimum": 0,
            "description": "여러 장을 촬영할 때 각 촬영 사이의 간격(s)",
        },
    },
    required=["count"],
)

RETURN_HOME_COMMAND = _command("return_home")

RECALL_POSITION_COMMAND = _command(
    "recall_position",
    properties={
        "target": {
            "type": "string",
            "enum": [
                "previous",
                "first",
            ],
            "description": (
                "previous는 직전 명령 위치, "
                "first는 첫 번째 명령 수행 위치"
            ),
        },
    },
    required=["target"],
)

CANCEL_COMMAND = _command("cancel")

EMERGENCY_STOP_COMMAND = _command("emergency_stop")


# ============================================================
# 드론 명령 출력 JSON Schema
# ============================================================

DRONE_COMMAND_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DroneCommandResult",
    "description": "자연어 드론 명령을 해석한 결과",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "accepted",
                "clarification_required",
                "unsupported",
                "invalid",
            ],
            "description": "명령 해석 결과 상태",
        },
        "commands": {
            "type": "array",
            "description": "사용자가 요청한 순서대로 정렬된 드론 명령 목록",
            "items": {
                "oneOf": [
                    ARM_COMMAND,
                    DISARM_COMMAND,
                    TAKEOFF_COMMAND,
                    LAND_COMMAND,
                    MOVE_RELATIVE_COMMAND,
                    MOVE_CLOCK_DIRECTION_COMMAND,
                    ROTATE_RELATIVE_COMMAND,
                    HOVER_COMMAND,
                    TAKE_PHOTO_COMMAND,
                    RETURN_HOME_COMMAND,
                    RECALL_POSITION_COMMAND,
                    CANCEL_COMMAND,
                    EMERGENCY_STOP_COMMAND,
                ],
            },
        },
        "message": {
            "type": ["string", "null"],
            "description": (
                "재질문 또는 오류 설명. "
                "accepted 상태에서는 null이어야 한다."
            ),
        },
    },
    "required": [
        "status",
        "commands",
        "message",
    ],
    "allOf": [
        {
            # 정상 명령은 명령을 하나 이상 포함하고 메시지가 없어야 한다.
            "if": {
                "properties": {
                    "status": {"const": "accepted"},
                },
                "required": ["status"],
            },
            "then": {
                "properties": {
                    "commands": {
                        "minItems": 1,
                    },
                    "message": {
                        "type": "null",
                    },
                },
            },
            # 나머지 상태에서는 실행할 명령이 없어야 하고
            # 사용자에게 보여줄 메시지가 있어야 한다.
            "else": {
                "properties": {
                    "commands": {
                        "maxItems": 0,
                    },
                    "message": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
            },
        },
    ],
}
