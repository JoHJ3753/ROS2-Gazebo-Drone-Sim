"""드론의 실행 완료 명령 기록 기능을 검증하는 테스트."""

from drone_control.action_history import ActionHistory


def make_move_command(
    direction: str = "forward",
    distance_m: float = 3.0,
) -> dict:
    """
    테스트에서 반복해서 사용할 이동 명령을 생성한다.

    실제 LLM Function Schema와 동일하게
    name과 arguments로 구성된 명령을 반환한다.
    """
    return {
        "name": "move_drone",
        "arguments": {
            "direction": direction,
            "distance_m": distance_m,
        },
    }


def make_rotate_command(yaw_deg: float = 90.0) -> dict:
    """테스트에서 사용할 상대 회전 명령을 생성한다."""
    return {
        "name": "rotate_relative",
        "arguments": {
            # 현재 스키마에서는 오른쪽 회전이 양수이고
            # 왼쪽 회전이 음수이다.
            "yaw_deg": yaw_deg,
        },
    }


def test_new_action_history_is_empty():
    """새 Action History에는 실행 기록이 없어야 한다."""
    history = ActionHistory()

    assert history.is_empty()
    assert history.get_actions() == []


def test_record_preserves_execution_order():
    """실행 완료 명령이 실제 실행 순서대로 저장되는지 확인한다."""
    history = ActionHistory()
    move_command = make_move_command()
    rotate_command = make_rotate_command()

    # FSM은 명령 실행이 성공한 이후에만 record를 호출한다.
    history.record(move_command)
    history.record(rotate_command)

    assert history.get_actions() == [
        move_command,
        rotate_command,
    ]


def test_get_actions_in_reverse_order():
    """경로 역추적 준비를 위해 기록을 역순으로 가져올 수 있어야 한다."""
    history = ActionHistory()
    first_command = make_move_command(direction="forward", distance_m=3.0)
    second_command = make_rotate_command(yaw_deg=90.0)
    third_command = make_move_command(direction="right", distance_m=2.0)

    history.record(first_command)
    history.record(second_command)
    history.record(third_command)

    # 이 메서드는 실행 순서만 뒤집는다.
    # 실제 반대 방향 명령 생성은 Reverse Executor가 담당한다.
    assert history.get_actions_in_reverse_order() == [
        third_command,
        second_command,
        first_command,
    ]


def test_clear_removes_all_actions():
    """새 임무 또는 recall 완료 시 기록을 초기화할 수 있어야 한다."""
    history = ActionHistory()
    history.record(make_move_command())
    history.record(make_rotate_command())

    history.clear()

    assert history.is_empty()
    assert history.get_actions() == []


def test_record_stores_independent_copy():
    """기록 후 원본 명령이 바뀌어도 저장된 기록은 변하지 않아야 한다."""
    history = ActionHistory()
    command = make_move_command(distance_m=3.0)

    history.record(command)

    # 외부에서 원본 딕셔너리를 수정하는 상황을 재현한다.
    command["arguments"]["distance_m"] = 100.0

    # Action History가 원본 객체를 그대로 보관하면 이 값도 100이 된다.
    # 안전한 기록을 위해 저장 당시 값인 3.0이 유지되어야 한다.
    saved_command = history.get_actions()[0]
    assert saved_command["arguments"]["distance_m"] == 3.0


def test_get_actions_returns_independent_copy():
    """조회 결과를 수정해도 내부 기록은 변하지 않아야 한다."""
    history = ActionHistory()
    history.record(make_move_command(distance_m=3.0))

    returned_actions = history.get_actions()

    # 호출자가 조회 결과를 수정하는 상황을 재현한다.
    returned_actions[0]["arguments"]["distance_m"] = 100.0
    returned_actions.append(make_rotate_command())

    # 내부 기록은 최초에 저장한 이동 명령 하나만 유지되어야 한다.
    saved_actions = history.get_actions()
    assert len(saved_actions) == 1
    assert saved_actions[0]["arguments"]["distance_m"] == 3.0
