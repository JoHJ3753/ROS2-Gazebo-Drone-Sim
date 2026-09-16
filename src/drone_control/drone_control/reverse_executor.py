"""실행 완료 명령을 역방향 명령으로 변환한다."""

from copy import deepcopy

from drone_control.action_history import Command


# 현재 Function Schema에서 사용하는 이동 방향의 반대 방향을 정의한다.
#
# 방향 변환 규칙을 한곳에 모아두면 조건문을 반복하지 않고,
# 새로운 방향이 추가됐을 때 수정 위치도 명확해진다.
OPPOSITE_DIRECTIONS = {
    "forward": "backward",
    "backward": "forward",
    "left": "right",
    "right": "left",
    "up": "down",
    "down": "up",
}


class ReverseExecutor:
    """
    Action History를 이용해 경로 역추적 명령을 생성한다.

    이 클래스는 명령을 실제로 실행하지 않는다.
    기존 명령의 순서와 방향을 반대로 변환한 실행 계획만 생성한다.
    """

    def reverse_action(self, action: Command) -> Command:
        """
        하나의 실행 완료 명령을 반대 방향 명령으로 변환한다.

        현재는 Function Schema의 기본 실행 명령인
        move_drone과 rotate_relative만 역변환할 수 있다.

        역변환을 지원하지 않는 명령 이름이나 이동 방향이 전달되면
        ValueError를 발생시킨다.
        """
        action_name = action.get("name")

        if action_name == "move_drone":
            return self._reverse_move(action)

        if action_name == "rotate_relative":
            return self._reverse_rotation(action)

        # 지원하지 않는 명령을 조용히 무시하면 recall 경로 일부가
        # 누락될 수 있으므로 즉시 오류를 발생시킨다.
        raise ValueError(
            f"Unsupported action for reverse execution: {action_name}"
        )

    def build_reverse_plan(
        self,
        actions: list[Command],
    ) -> list[Command]:
        """
        실행 기록 전체를 역추적하기 위한 명령 목록을 생성한다.

        마지막으로 실행한 동작부터 반대로 실행해야 원래 경로를
        되돌아갈 수 있으므로 기록 순서를 먼저 뒤집는다.
        """
        return [
            self.reverse_action(action)
            for action in reversed(actions)
        ]

    def _reverse_move(self, action: Command) -> Command:
        """이동 명령의 방향을 반대 방향으로 변환한다."""
        reversed_action = deepcopy(action)
        arguments = reversed_action["arguments"]
        direction = arguments["direction"]

        try:
            reverse_direction = OPPOSITE_DIRECTIONS[direction]
        except KeyError as error:
            # Schema 검증 이후에는 일반적으로 발생하지 않지만,
            # 잘못된 내부 명령이 전달된 경우 원인을 명확히 알린다.
            raise ValueError(
                f"Unsupported move direction: {direction}"
            ) from error

        # 거리와 선택 속도는 유지하고 방향만 반대로 바꾼다.
        arguments["direction"] = reverse_direction
        return reversed_action

    def _reverse_rotation(self, action: Command) -> Command:
        """상대 회전각의 부호를 반대로 변환한다."""
        reversed_action = deepcopy(action)
        arguments = reversed_action["arguments"]

        # 현재 Function Schema에서는 오른쪽이 양수이고 왼쪽이 음수다.
        # 부호만 반전하면 같은 각도와 속도로 반대 방향 회전이 된다.
        arguments["yaw_deg"] = -arguments["yaw_deg"]
        return reversed_action
