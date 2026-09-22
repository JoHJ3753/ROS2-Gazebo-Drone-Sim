"""
드론 명령 JSON Schema 검증 테스트.

이 파일은 LLM이 생성한 명령이 DRONE_COMMAND_SCHEMA 규칙에 맞는지 확인한다.

검사 대상:
- 정상적인 명령이 허용되는지
- 필수 인자가 없는 명령이 거부되는지
- 잘못된 방향과 거리가 거부되는지
- status, commands, message 사이의 관계가 지켜지는지

이 테스트는 실제 드론이나 ROS 2 노드를 실행하지 않는다.
JSON 데이터 구조만 검사하는 단위 테스트다.
"""

# pytest는 테스트 실행과 예외 발생 여부 검증에 사용한다.
import pytest

# ROS 2 Humble에 기본 설치된 jsonschema 3.2.0이 지원하는 검증기다.
from jsonschema import Draft7Validator

# 잘못된 JSON 데이터가 입력됐을 때 발생하는 예외다.
from jsonschema.exceptions import ValidationError

# 실제 프로그램에서 사용하는 드론 명령 스키마를 가져온다.
# 테스트용 스키마를 별도로 만들지 않기 때문에 실제 코드와 동일한 규칙을 검사한다.
from drone_command_interface.schemas import DRONE_COMMAND_SCHEMA


# 실제 프로젝트 스키마를 Draft 7 규칙으로 검사한다.
VALIDATOR = Draft7Validator(DRONE_COMMAND_SCHEMA)


def validate(result: dict) -> None:
    """
    주어진 명령 결과가 DRONE_COMMAND_SCHEMA에 맞는지 검증한다.

    Args:
        result:
            LLM이 출력했다고 가정하는 드론 명령 딕셔너리.

    Raises
    ------
    ValidationError
        필수 필드가 없거나 값이 스키마 규칙에 맞지 않는 경우.

    """
    VALIDATOR.validate(result)


# ============================================================
# JSON Schema 자체 검사
# ============================================================


def test_schema_itself_is_valid():
    """
    DRONE_COMMAND_SCHEMA 자체가 올바른 JSON Schema인지 확인한다.

    명령 데이터가 아니라 스키마 정의 자체의 문법과 구조를 검사한다.
    예외가 발생하지 않으면 테스트가 성공한다.
    """
    # 명령 데이터뿐 아니라 스키마 정의 자체도 Draft 7 규격에 맞는지 검사한다.
    Draft7Validator.check_schema(DRONE_COMMAND_SCHEMA)


# ============================================================
# 정상적인 이동 명령 검사
# ============================================================


@pytest.mark.parametrize(
    "direction",
    [
        "forward",
        "backward",
        "left",
        "right",
        "up",
        "down",
    ],
)
def test_valid_move_drone_directions(direction):
    """
    스키마에 정의된 여섯 방향이 모두 허용되는지 확인한다.

    pytest.mark.parametrize를 사용하면 같은 테스트를 각 방향에 대해
    반복해서 실행할 수 있다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    # 테스트가 반복될 때마다 여섯 방향 중 하나가 들어간다.
                    "direction": direction,
                    "distance_m": 3.0,
                },
            },
        ],
        # accepted 상태에서는 오류나 재질문이 없으므로 None을 사용한다.
        # Python의 None은 JSON의 null에 해당한다.
        "message": None,
    }

    # 정상 명령이므로 예외가 발생하지 않아야 한다.
    validate(result)


def test_valid_move_drone_with_speed():
    """
    이동 속도가 포함된 정상적인 move_drone 명령을 검사한다.

    speed_mps는 선택 인자이므로 있어도 되고 없어도 된다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",
                    "distance_m": 3.0,
                    "speed_mps": 1.0,
                },
            },
        ],
        "message": None,
    }

    # 허용된 선택 인자이므로 검증을 통과해야 한다.
    validate(result)


# ============================================================
# 잘못된 이동 거리 검사
# ============================================================


@pytest.mark.parametrize(
    "distance_m",
    [
        0.0,
        -1.0,
    ],
)
def test_move_drone_rejects_non_positive_distance(distance_m):
    """
    0 또는 음수인 이동 거리가 거부되는지 확인한다.

    이동 방향은 direction으로 표현하므로 distance_m은 항상
    0보다 큰 양수여야 한다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",

                    # 오류 검사를 위해 0 또는 음수를 의도적으로 넣는다.
                    "distance_m": distance_m,
                },
            },
        ],
        "message": None,
    }

    # 잘못된 거리이므로 ValidationError가 발생해야 테스트가 성공한다.
    with pytest.raises(ValidationError):
        validate(result)


# ============================================================
# 잘못된 이동 방향 검사
# ============================================================


def test_move_drone_rejects_unknown_direction():
    """
    스키마에 정의되지 않은 이동 방향이 거부되는지 확인한다.

    현재 허용되는 방향은 다음 여섯 가지다.
    forward, backward, left, right, up, down
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    # diagonal은 스키마에 없는 방향이므로 잘못된 값이다.
                    "direction": "diagonal",
                    "distance_m": 3.0,
                },
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


# ============================================================
# 필수 인자 검사
# ============================================================


def test_move_drone_requires_direction():
    """
    move_drone 명령에 direction이 반드시 필요한지 확인한다.

    direction을 의도적으로 생략했으므로 검증에 실패해야 한다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    "distance_m": 3.0,
                },
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


def test_move_drone_requires_distance():
    """
    move_drone 명령에 distance_m이 반드시 필요한지 확인한다.

    distance_m을 의도적으로 생략했으므로 검증에 실패해야 한다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",
                },
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


def test_move_drone_rejects_additional_argument():
    """
    스키마에 정의되지 않은 추가 인자가 거부되는지 확인한다.

    arguments의 additionalProperties가 False이므로
    unknown_argument를 허용하면 안 된다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",
                    "distance_m": 3.0,

                    # 거부 여부를 확인하기 위해 존재하지 않는 인자를 넣는다.
                    "unknown_argument": True,
                },
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


# ============================================================
# accepted 상태 검사
# ============================================================


def test_accepted_requires_at_least_one_command():
    """
    Accepted 상태에는 실행할 명령이 하나 이상 필요한지 확인한다.

    accepted인데 commands가 비어 있으면 의미가 모순되므로
    스키마 검증에 실패해야 한다.
    """
    result = {
        "status": "accepted",
        "commands": [],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


def test_accepted_requires_null_message():
    """
    Accepted 상태에서 message가 반드시 null인지 확인한다.

    accepted는 정상적으로 명령을 생성했다는 의미이므로
    오류 또는 재질문 메시지를 포함하면 안 된다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "land",
                "arguments": {},
            },
        ],

        # 오류 검사를 위해 문자열을 의도적으로 넣는다.
        "message": "착륙합니다.",
    }

    with pytest.raises(ValidationError):
        validate(result)


# ============================================================
# accepted가 아닌 상태 검사
# ============================================================


@pytest.mark.parametrize(
    "status",
    [
        "clarification_required",
        "unsupported",
        "invalid",
    ],
)
def test_non_accepted_status_requires_empty_commands(status):
    """
    accepted가 아닌 상태에서 commands가 비어 있어야 하는지 확인한다.

    실행할 수 없는 상태인데 명령이 포함되면 실제 드론이 잘못된
    명령을 수행할 위험이 있으므로 반드시 거부해야 한다.
    """
    result = {
        "status": status,

        # 오류 검사를 위해 실행 명령을 의도적으로 포함한다.
        "commands": [
            {
                "name": "land",
                "arguments": {},
            },
        ],
        "message": "명령을 실행할 수 없습니다.",
    }

    with pytest.raises(ValidationError):
        validate(result)


@pytest.mark.parametrize(
    "status",
    [
        "clarification_required",
        "unsupported",
        "invalid",
    ],
)
def test_non_accepted_status_requires_message(status):
    """
    accepted가 아닌 상태에 설명 메시지가 필요한지 확인한다.

    사용자가 재질문 또는 실패 이유를 알 수 있도록
    message는 비어 있지 않은 문자열이어야 한다.
    """
    result = {
        "status": status,
        "commands": [],

        # 빈 문자열은 유효한 안내 메시지가 아니므로 거부되어야 한다.
        "message": "",
    }

    with pytest.raises(ValidationError):
        validate(result)


def test_valid_clarification_result():
    """
    필요한 정보가 부족한 경우의 정상적인 재질문 결과를 검사한다.

    clarification_required 상태에서는 commands가 비어 있고
    message에 구체적인 질문이 있어야 한다.
    """
    result = {
        "status": "clarification_required",
        "commands": [],
        "message": "이동할 거리를 미터 단위로 입력해 주세요.",
    }

    # 상태, 빈 명령 목록, 안내 메시지가 올바르므로 통과해야 한다.
    validate(result)


# ============================================================
# 알 수 없는 명령 검사
# ============================================================


def test_unknown_command_is_rejected():
    """
    스키마에 정의되지 않은 명령 이름이 거부되는지 확인한다.

    LLM이 존재하지 않는 명령을 만들어내는 환각을 방지하기 위한 테스트다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                # fly_to_moon은 정의되지 않은 명령이다.
                "name": "fly_to_moon",
                "arguments": {},
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)


# ============================================================
# 복합 명령 검사
# ============================================================


def test_valid_composite_command():
    """
    여러 명령이 순서대로 포함된 복합 명령을 검사한다.

    다음 명령이 사용자 요청 순서대로 들어 있다고 가정한다.

    1. 2m 높이로 이륙
    2. 앞으로 3m 이동
    3. 사진 한 장 촬영
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "takeoff",
                "arguments": {
                    "altitude_m": 2.0,
                },
            },
            {
                "name": "move_drone",
                "arguments": {
                    "direction": "forward",
                    "distance_m": 3.0,
                },
            },
            {
                "name": "take_photo",
                "arguments": {
                    "count": 1,
                },
            },
        ],
        "message": None,
    }

    # 세 명령이 모두 유효하므로 전체 결과도 통과해야 한다.
    validate(result)


# ============================================================
# 취소 및 비상 정지 단독 명령 검사
# ============================================================


@pytest.mark.parametrize(
    "exclusive_command",
    [
        "cancel",
        "emergency_stop",
    ],
)
def test_exclusive_command_is_valid_when_used_alone(exclusive_command):
    """
    cancel과 emergency_stop이 단독으로 사용되면 허용되는지 확인한다.

    두 명령은 다른 명령과 함께 사용할 수 없지만,
    각각 하나만 출력되는 경우에는 정상적인 명령이다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": exclusive_command,
                "arguments": {},
            },
        ],
        "message": None,
    }

    # 단독 명령이므로 스키마 검증을 통과해야 한다.
    validate(result)


@pytest.mark.parametrize(
    "exclusive_command",
    [
        "cancel",
        "emergency_stop",
    ],
)
def test_exclusive_command_rejects_other_commands(exclusive_command):
    """
    Cancel 또는 emergency_stop이 다른 명령과 함께 있으면 거부하는지 확인한다.

    전용 명령이 배열의 앞이나 뒤에 있어도 동일하게 거부되어야 하므로
    두 가지 순서를 모두 검사한다.
    """
    exclusive = {
        "name": exclusive_command,
        "arguments": {},
    }
    land = {
        "name": "land",
        "arguments": {},
    }

    # 전용 명령이 먼저 나오는 경우와 나중에 나오는 경우를 모두 검사한다.
    command_orders = [
        [exclusive, land],
        [land, exclusive],
    ]

    for commands in command_orders:
        result = {
            "status": "accepted",
            "commands": commands,
            "message": None,
        }

        # cancel 또는 emergency_stop이 다른 명령과 함께 있으므로
        # ValidationError가 발생해야 테스트가 성공한다.
        with pytest.raises(ValidationError):
            validate(result)


# ============================================================
# 홈 복귀 및 경로 역추적 명령 검사
# ============================================================


def test_valid_return_home_command():
    """
    홈 좌표로 직접 복귀하는 return_home 명령을 허용하는지 확인한다.

    return_home의 실제 좌표 계산과 이동은 Control Layer가 담당하므로
    LLM 출력에는 별도의 인자가 필요하지 않다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "return_home",
                "arguments": {},
            },
        ],
        "message": None,
    }

    validate(result)


def test_valid_recall_command():
    """
    Action History를 역추적하는 recall 단독 명령을 허용하는지 확인한다.

    역방향 이동 목록은 Reverse Executor가 생성하므로
    recall 명령 자체에는 별도의 인자가 필요하지 않다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "recall",
                "arguments": {},
            },
        ],
        "message": None,
    }

    validate(result)


def test_valid_recall_then_land_command():
    """
    경로를 역추적한 다음 착륙하는 복합 명령을 허용하는지 확인한다.

    commands 배열의 순서는 실제 실행 순서를 의미하므로
    recall이 land보다 먼저 위치해야 한다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "recall",
                "arguments": {},
            },
            {
                "name": "land",
                "arguments": {},
            },
        ],
        "message": None,
    }

    validate(result)


def test_old_recall_position_command_is_rejected():
    """
    더 이상 사용하지 않는 recall_position 명령을 거부하는지 확인한다.

    이전 명령 이름이 실수로 다시 사용되는 것을 방지하는 회귀 테스트다.
    """
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "recall_position",
                "arguments": {
                    "target": "previous",
                },
            },
        ],
        "message": None,
    }

    with pytest.raises(ValidationError):
        validate(result)
