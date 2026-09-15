"""
드론 명령 출력 형식을 정의하는 JSON Schema 모듈.

사용자의 자연어 명령을 Qwen 모델이 해석하면 다음 세 가지 정보를
포함하는 JSON 객체를 출력한다.

- status: 명령 해석 결과
- commands: 실행할 드론 명령 목록
- message: 재질문 또는 오류 메시지

이 파일은 명령을 직접 실행하지 않는다.
출력 데이터가 올바른 형식인지 검사하기 위한 규칙만 정의한다.
"""

from typing import Any


def _command(
    name: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """
    하나의 드론 명령에 대한 공통 JSON Schema를 생성한다.

    Args:
        name:
            명령 이름. 예: takeoff, land, move_drone

        properties:
            명령이 받을 수 있는 인자들의 스키마.
            예: takeoff 명령의 altitude_m

        required:
            반드시 포함되어야 하는 인자 이름 목록.

    Returns:
        name과 arguments를 갖는 명령 객체의 JSON Schema.
    """
    # 모든 명령의 세부 인자는 arguments 객체 안에 저장한다.
    arguments: dict[str, Any] = {
        "type": "object",

        # 스키마에 정의되지 않은 인자가 들어오는 것을 차단한다.
        "additionalProperties": False,

        # properties가 전달되지 않은 명령은 빈 인자 객체를 사용한다.
        "properties": properties or {},
    }

    # 필수 인자가 있는 명령에만 required 항목을 추가한다.
    if required:
        arguments["required"] = required

    # 모든 명령은 동일하게 name과 arguments를 갖는다.
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            # const는 이 명령에서 허용되는 이름을 하나로 고정한다.
            "name": {"const": name},
            "arguments": arguments,
        },
        "required": ["name", "arguments"],
    }


# ============================================================
# 개별 드론 명령 스키마
# ============================================================

# 드론 모터를 활성화하는 명령이다.
# 별도의 인자를 받지 않는다.
ARM_COMMAND = _command("arm")

# 드론 모터를 비활성화하는 명령이다.
# 별도의 인자를 받지 않는다.
DISARM_COMMAND = _command("disarm")

# 지정한 목표 고도까지 이륙하는 명령이다.
# altitude_m은 반드시 0보다 커야 한다.
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

# 자연어에서 추출한 이동 방향과 거리를 표현하는 LLM용 명령이다.
#
# 예:
#   direction="forward", distance_m=2.0 → 앞으로 2m
#   direction="left", distance_m=1.0    → 왼쪽으로 1m
#   direction="up", distance_m=0.5      → 위로 0.5m
#
# LLM은 방향을 좌표축이나 양수·음수로 변환하지 않는다.
# 실제 forward_m, right_m, up_m 변환은 CoordinateCalculator가 담당한다.
MOVE_DRONE_COMMAND = _command(
    "move_drone",
    properties={
        "direction": {
            "type": "string",
            "enum": [
                "forward",
                "backward",
                "left",
                "right",
                "up",
                "down",
            ],
            "description": "드론이 이동할 상대 방향",
        },
        "distance_m": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "이동할 거리(m)",
        },
        "speed_mps": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "사용자가 명시한 이동 속도(m/s). 지정하지 않은 경우 생략",
        },
    },
    required=[
        "direction",
        "distance_m",
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
    # ROS 2 Humble의 기본 jsonschema 3.2.0과 호환되는 Draft 7을 사용한다.
    "$schema": "http://json-schema.org/draft-07/schema#",
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
                    MOVE_DRONE_COMMAND,
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
    # 여러 필드 사이의 관계처럼 properties만으로 표현할 수 없는
    # 추가 검증 규칙을 모두 적용한다.
    "allOf": [
        {
            # ====================================================
            # status에 따른 commands와 message 검증
            # ====================================================
            "if": {
                # status가 accepted인지 확인한다.
                "properties": {
                    "status": {"const": "accepted"},
                },
                "required": ["status"],
            },
            "then": {
                # 정상 명령에는 실행할 명령이 하나 이상 있어야 하며
                # 오류나 재질문 메시지가 없어야 한다.
                "properties": {
                    "commands": {
                        "minItems": 1,
                    },
                    "message": {
                        "type": "null",
                    },
                },
            },
            "else": {
                # clarification_required, unsupported, invalid 상태에서는
                # 실행 명령이 없어야 하고 사용자 안내 메시지가 필요하다.
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
        {
            # ====================================================
            # cancel과 emergency_stop의 단독 출력 검증
            # ====================================================
            "if": {
                "properties": {
                    "commands": {
                        # contains는 배열 안에 아래 조건을 만족하는 항목이
                        # 하나 이상 있는지 검사한다.
                        "contains": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "enum": [
                                        "cancel",
                                        "emergency_stop",
                                    ],
                                },
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["commands"],
            },
            "then": {
                "properties": {
                    # cancel 또는 emergency_stop이 발견되면 commands 배열에는
                    # 해당 명령 하나만 존재해야 한다.
                    "commands": {
                        "maxItems": 1,
                    },
                },
            },
        },
    ],
}