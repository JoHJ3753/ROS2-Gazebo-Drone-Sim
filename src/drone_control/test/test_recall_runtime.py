"""Recall 순차 실행 상태 관리자를 검증한다."""

import pytest

from drone_control.recall_runtime import RecallRuntime
from drone_control.recall_runtime import RecallRuntimeError


def make_move(direction: str, distance_m: float) -> dict:
    """테스트용 상대이동 명령을 생성한다."""
    return {
        "name": "move_drone",
        "arguments": {
            "direction": direction,
            "distance_m": distance_m,
        },
    }


def make_rotation(yaw_deg: float) -> dict:
    """테스트용 상대회전 명령을 생성한다."""
    return {
        "name": "rotate_relative",
        "arguments": {"yaw_deg": yaw_deg},
    }


def test_recall_executes_reverse_plan_one_step_at_a_time() -> None:
    """마지막 동작부터 한 단계씩 반대 명령을 반환한다."""
    runtime = RecallRuntime()
    runtime.record_completed_action(make_move("forward", 2.0))
    runtime.record_completed_action(make_rotation(90.0))

    first = runtime.start()
    second = runtime.complete_step()
    completed = runtime.complete_step()

    assert first == make_rotation(-90.0)
    assert second == make_move("backward", 2.0)
    assert completed is None
    assert runtime.active is False
    assert runtime.get_history() == []


def test_recall_rejects_empty_history() -> None:
    """되돌릴 명령이 없으면 Recall을 시작하지 않는다."""
    with pytest.raises(RecallRuntimeError, match="History is empty"):
        RecallRuntime().start()


def test_aborted_recall_invalidates_stale_history() -> None:
    """부분 실행 뒤 잘못된 재시도를 막도록 기존 이력을 제거한다."""
    runtime = RecallRuntime()
    original = make_move("left", 1.0)
    runtime.record_completed_action(original)
    runtime.start()

    runtime.abort()

    assert runtime.active is False
    assert runtime.get_history() == []


def test_recall_steps_are_not_recorded_as_new_history() -> None:
    """역추적 중 실행한 반대 명령이 이력에 다시 쌓이지 않는다."""
    runtime = RecallRuntime()
    runtime.record_completed_action(make_move("forward", 1.0))
    runtime.start()

    with pytest.raises(RecallRuntimeError, match="must not be added"):
        runtime.record_completed_action(make_move("backward", 1.0))
