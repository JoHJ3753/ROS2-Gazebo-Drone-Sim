"""Mission FSM의 상태 전환과 명령 기록 동작을 검증한다."""

import pytest

from drone_control.action_history import ActionHistory
from drone_control.mission_fsm import (
    InvalidStateTransitionError,
    MissionFSM,
    MissionState,
)
from drone_control.reverse_executor import ReverseExecutor


def make_move_command(
    direction: str = "forward",
    distance_m: float = 3.0,
) -> dict:
    """현재 Function Schema 형식의 이동 명령을 생성한다."""
    return {
        "name": "move_drone",
        "arguments": {
            "direction": direction,
            "distance_m": distance_m,
        },
    }


def make_rotate_command(yaw_deg: float = 90.0) -> dict:
    """현재 Function Schema 형식의 상대 회전 명령을 생성한다."""
    return {
        "name": "rotate_relative",
        "arguments": {
            "yaw_deg": yaw_deg,
        },
    }


def move_to_flying_state(fsm: MissionFSM) -> None:
    """테스트용 FSM을 정상 비행 상태로 전환한다."""
    fsm.start_takeoff()
    fsm.complete_takeoff(success=True)


@pytest.fixture
def fsm_components() -> tuple[MissionFSM, ActionHistory]:
    """서로 연결된 Mission FSM과 Action History를 생성한다."""
    history = ActionHistory()
    reverse_executor = ReverseExecutor()
    fsm = MissionFSM(
        action_history=history,
        reverse_executor=reverse_executor,
    )
    return fsm, history


def test_initial_state_is_idle(fsm_components):
    """새 Mission FSM은 대기 상태에서 시작해야 한다."""
    fsm, _ = fsm_components

    assert fsm.state is MissionState.IDLE


def test_successful_takeoff_changes_state_to_flying(fsm_components):
    """이륙이 성공하면 비행 상태로 전환해야 한다."""
    fsm, history = fsm_components

    # 이전 임무 기록이 남은 상황을 재현한다.
    history.record(make_move_command())

    fsm.start_takeoff()

    assert fsm.state is MissionState.TAKING_OFF

    fsm.complete_takeoff(success=True)

    assert fsm.state is MissionState.FLYING

    # 새 비행이 시작되면 이전 임무의 경로를 사용하지 않도록 초기화한다.
    assert history.is_empty()


def test_failed_takeoff_changes_state_to_error(fsm_components):
    """이륙이 실패하면 오류 상태로 전환해야 한다."""
    fsm, _ = fsm_components

    fsm.start_takeoff()
    fsm.complete_takeoff(success=False)

    assert fsm.state is MissionState.ERROR


def test_successful_action_is_recorded(fsm_components):
    """비행 중 성공한 이동 명령은 Action History에 기록해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    command = make_move_command(direction="forward", distance_m=3.0)

    fsm.start_action(command)

    assert fsm.state is MissionState.EXECUTING

    fsm.complete_action(success=True)

    assert fsm.state is MissionState.FLYING
    assert history.get_actions() == [command]


def test_failed_action_is_not_recorded(fsm_components):
    """실패한 이동 명령은 Action History에 기록하지 않아야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)

    fsm.start_action(make_move_command())
    fsm.complete_action(success=False)

    assert fsm.state is MissionState.ERROR
    assert history.is_empty()


def test_non_reversible_action_is_not_recorded(fsm_components):
    """호버처럼 역변환하지 않는 명령은 경로 기록에서 제외해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    hover_command = {
        "name": "hover",
        "arguments": {
            "duration_s": 2.0,
        },
    }

    fsm.start_action(hover_command)
    fsm.complete_action(success=True)

    assert fsm.state is MissionState.FLYING
    assert history.is_empty()


def test_start_action_is_rejected_while_idle(fsm_components):
    """이륙하지 않은 상태에서는 이동 명령을 시작할 수 없어야 한다."""
    fsm, _ = fsm_components

    with pytest.raises(InvalidStateTransitionError):
        fsm.start_action(make_move_command())

    assert fsm.state is MissionState.IDLE


def test_recall_builds_reverse_plan(fsm_components):
    """Recall을 시작하면 실행 기록의 역방향 계획을 생성해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)

    history.record(
        make_move_command(direction="forward", distance_m=3.0)
    )
    history.record(make_rotate_command(yaw_deg=90.0))

    reverse_plan = fsm.start_recall()

    assert fsm.state is MissionState.RECALLING
    assert reverse_plan == [
        make_rotate_command(yaw_deg=-90.0),
        make_move_command(direction="backward", distance_m=3.0),
    ]


def test_recall_is_rejected_when_history_is_empty(fsm_components):
    """실행 기록이 없으면 Recall을 시작할 수 없어야 한다."""
    fsm, _ = fsm_components
    move_to_flying_state(fsm)

    with pytest.raises(InvalidStateTransitionError):
        fsm.start_recall()

    # Recall을 시작하지 못했으므로 기존 비행 상태를 유지한다.
    assert fsm.state is MissionState.FLYING


def test_successful_recall_clears_history(fsm_components):
    """Recall이 성공하면 기존 실행 기록을 초기화해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    history.record(make_move_command())

    fsm.start_recall()
    fsm.complete_recall(success=True)

    # Recall은 경로 복귀만 수행하며 자동 착륙하지 않는다.
    assert fsm.state is MissionState.FLYING
    assert history.is_empty()


def test_failed_recall_preserves_history(fsm_components):
    """Recall 실패 시 재시도와 원인 확인을 위해 기록을 보존해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    original_command = make_move_command()
    history.record(original_command)

    fsm.start_recall()
    fsm.complete_recall(success=False)

    assert fsm.state is MissionState.ERROR
    assert history.get_actions() == [original_command]


def test_successful_return_home_clears_old_history(fsm_components):
    """직접 홈 복귀가 성공하면 이전 경로 기록을 초기화해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    history.record(make_move_command())

    fsm.start_return_home()

    assert fsm.state is MissionState.RETURNING_HOME

    fsm.complete_return_home(success=True)

    # 홈 위치로 직접 이동했으므로 기존 경로는 현재 위치와 맞지 않는다.
    assert fsm.state is MissionState.FLYING
    assert history.is_empty()


def test_failed_return_home_changes_state_to_error(fsm_components):
    """직접 홈 복귀가 실패하면 오류 상태로 전환해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    original_command = make_move_command()
    history.record(original_command)

    fsm.start_return_home()
    fsm.complete_return_home(success=False)

    assert fsm.state is MissionState.ERROR

    # 실패 시에는 원인 확인을 위해 기존 기록을 보존한다.
    assert history.get_actions() == [original_command]


def test_successful_landing_changes_state_to_idle(fsm_components):
    """착륙이 성공하면 대기 상태로 돌아가고 기록을 초기화해야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)
    history.record(make_move_command())

    fsm.start_landing()

    assert fsm.state is MissionState.LANDING

    fsm.complete_landing(success=True)

    assert fsm.state is MissionState.IDLE
    assert history.is_empty()


def test_failed_landing_changes_state_to_error(fsm_components):
    """착륙이 실패하면 오류 상태로 전환해야 한다."""
    fsm, _ = fsm_components
    move_to_flying_state(fsm)

    fsm.start_landing()
    fsm.complete_landing(success=False)

    assert fsm.state is MissionState.ERROR


def test_emergency_stop_has_priority_over_current_action(fsm_components):
    """명령 실행 중에도 긴급 정지 상태로 즉시 전환할 수 있어야 한다."""
    fsm, history = fsm_components
    move_to_flying_state(fsm)

    fsm.start_action(make_move_command())

    assert fsm.state is MissionState.EXECUTING

    fsm.emergency_stop()

    assert fsm.state is MissionState.EMERGENCY_STOPPED

    # 긴급 정지된 미완료 명령은 성공 기록으로 저장하면 안 된다.
    assert history.is_empty()


def test_completion_is_rejected_from_wrong_state(fsm_components):
    """시작하지 않은 동작의 완료 처리를 허용하지 않아야 한다."""
    fsm, _ = fsm_components

    with pytest.raises(InvalidStateTransitionError):
        fsm.complete_takeoff(success=True)

    with pytest.raises(InvalidStateTransitionError):
        fsm.complete_action(success=True)

    with pytest.raises(InvalidStateTransitionError):
        fsm.complete_recall(success=True)

    with pytest.raises(InvalidStateTransitionError):
        fsm.complete_return_home(success=True)

    with pytest.raises(InvalidStateTransitionError):
        fsm.complete_landing(success=True)
