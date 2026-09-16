"""드론이 성공적으로 실행한 명령을 순서대로 관리한다."""

from copy import deepcopy
from typing import Any


# Function Schema에서 사용하는 하나의 명령 구조를 나타낸다.
#
# 예:
# {
#     "name": "move_drone",
#     "arguments": {
#         "direction": "forward",
#         "distance_m": 3.0,
#     },
# }
Command = dict[str, Any]


class ActionHistory:
    """
    드론이 성공적으로 실행한 명령의 기록을 관리한다.

    이 클래스는 명령의 실행 성공 여부를 판단하지 않는다.
    Mission FSM이 명령 실행 성공을 확인한 뒤 record를 호출해야 한다.

    또한 역방향 명령을 직접 생성하지 않는다.
    실제 반대 방향 계산은 Reverse Executor가 담당한다.
    """

    def __init__(self) -> None:
        """비어 있는 명령 기록을 생성한다."""
        self._actions: list[Command] = []

    def record(self, command: Command) -> None:
        """
        실행이 완료된 명령을 기록한다.

        호출자가 나중에 원본 명령을 수정하더라도 저장된 기록이
        변하지 않도록 깊은 복사본을 저장한다.
        """
        self._actions.append(deepcopy(command))

    def get_actions(self) -> list[Command]:
        """
        기록된 명령을 실행 순서대로 반환한다.

        반환된 값을 외부에서 수정해도 내부 기록이 손상되지 않도록
        깊은 복사본을 반환한다.
        """
        return deepcopy(self._actions)

    def get_actions_in_reverse_order(self) -> list[Command]:
        """
        기록된 명령을 실행 순서의 역순으로 반환한다.

        이 메서드는 순서만 뒤집는다.
        이동 방향이나 회전각의 부호를 바꾸는 작업은 하지 않는다.
        """
        reversed_actions = list(reversed(self._actions))
        return deepcopy(reversed_actions)

    def clear(self) -> None:
        """
        저장된 모든 명령 기록을 제거한다.

        새 비행 임무를 시작하거나 recall을 성공적으로 완료한 뒤
        이전 경로가 다시 사용되지 않도록 호출한다.
        """
        self._actions.clear()

    def is_empty(self) -> bool:
        """저장된 명령이 없으면 True를 반환한다."""
        return not self._actions
