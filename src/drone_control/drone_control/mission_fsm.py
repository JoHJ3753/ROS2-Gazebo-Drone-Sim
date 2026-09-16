"""드론 임무의 실행 상태와 상태 전환을 관리한다."""

from copy import deepcopy
from enum import Enum

from drone_control.action_history import ActionHistory, Command
from drone_control.reverse_executor import ReverseExecutor


# Recall에서 되돌릴 수 있는 기본 실행 명령만 경로 기록에 저장한다.
#
# hover와 take_photo 같은 명령은 실행할 수 있지만 위치 복귀에 필요한
# 이동 경로가 아니므로 Action History에는 기록하지 않는다.
REVERSIBLE_ACTION_NAMES = frozenset(
    {
        "move_drone",
        "rotate_relative",
    }
)


class MissionState(Enum):
    """Mission FSM에서 사용하는 상태를 정의한다."""

    IDLE = "idle"
    TAKING_OFF = "taking_off"
    FLYING = "flying"
    EXECUTING = "executing"
    RECALLING = "recalling"
    RETURNING_HOME = "returning_home"
    LANDING = "landing"
    EMERGENCY_STOPPED = "emergency_stopped"
    ERROR = "error"


class InvalidStateTransitionError(RuntimeError):
    """현재 상태에서 허용되지 않는 전환을 요청하면 발생한다."""


class MissionFSM:
    """
    드론 임무의 상태 전환과 실행 기록을 관리한다.

    이 클래스는 실제 드론 제어 명령을 PX4에 전송하지 않는다.
    명령을 시작하거나 완료했을 때 상태를 변경하고, 성공한 이동 및
    회전 명령을 Action History에 기록한다.
    """

    def __init__(
        self,
        action_history: ActionHistory,
        reverse_executor: ReverseExecutor,
    ) -> None:
        """필요한 실행 기록과 역추적기를 연결해 FSM을 생성한다."""
        self._state = MissionState.IDLE
        self._action_history = action_history
        self._reverse_executor = reverse_executor
        self._current_action: Command | None = None

    @property
    def state(self) -> MissionState:
        """현재 Mission FSM 상태를 반환한다."""
        return self._state

    def start_takeoff(self) -> None:
        """대기 상태에서 이륙을 시작한다."""
        self._require_state(
            MissionState.IDLE,
            operation="start_takeoff",
        )
        self._state = MissionState.TAKING_OFF

    def complete_takeoff(self, success: bool) -> None:
        """이륙 결과에 따라 비행 또는 오류 상태로 전환한다."""
        self._require_state(
            MissionState.TAKING_OFF,
            operation="complete_takeoff",
        )

        if success:
            # 새로운 비행이 시작되면 이전 임무의 경로를 제거한다.
            self._action_history.clear()
            self._state = MissionState.FLYING
            return

        self._state = MissionState.ERROR

    def start_action(self, action: Command) -> None:
        """비행 상태에서 일반 명령 실행을 시작한다."""
        self._require_state(
            MissionState.FLYING,
            operation="start_action",
        )

        # 호출자가 실행 중인 명령 객체를 수정해도 완료 시 기록되는
        # 값이 변하지 않도록 독립된 복사본을 보관한다.
        self._current_action = deepcopy(action)
        self._state = MissionState.EXECUTING

    def complete_action(self, success: bool) -> None:
        """현재 일반 명령의 실행 결과를 처리한다."""
        self._require_state(
            MissionState.EXECUTING,
            operation="complete_action",
        )

        current_action = self._current_action
        self._current_action = None

        if not success:
            self._state = MissionState.ERROR
            return

        # EXECUTING 상태에는 항상 현재 명령이 존재해야 한다.
        # 방어적으로 None을 확인해 내부 상태 오류를 명확하게 처리한다.
        if current_action is None:
            self._state = MissionState.ERROR
            raise RuntimeError(
                "Current action is missing while completing an action"
            )

        if current_action.get("name") in REVERSIBLE_ACTION_NAMES:
            self._action_history.record(current_action)

        self._state = MissionState.FLYING

    def start_recall(self) -> list[Command]:
        """저장된 실행 경로를 이용해 역추적 계획을 생성한다."""
        self._require_state(
            MissionState.FLYING,
            operation="start_recall",
        )

        if self._action_history.is_empty():
            raise InvalidStateTransitionError(
                "Cannot start recall because Action History is empty"
            )

        # 계획 생성에 실패하면 FLYING 상태를 유지하도록
        # 상태 변경 전에 역방향 명령 목록을 먼저 생성한다.
        reverse_plan = self._reverse_executor.build_reverse_plan(
            self._action_history.get_actions()
        )
        self._state = MissionState.RECALLING
        return reverse_plan

    def complete_recall(self, success: bool) -> None:
        """경로 역추적 결과에 따라 기록과 상태를 갱신한다."""
        self._require_state(
            MissionState.RECALLING,
            operation="complete_recall",
        )

        if success:
            # 역추적이 끝났으므로 기존 경로를 다시 사용하지 않는다.
            self._action_history.clear()
            self._state = MissionState.FLYING
            return

        # 실패 기록은 재시도나 원인 확인에 사용할 수 있도록 보존한다.
        self._state = MissionState.ERROR

    def start_return_home(self) -> None:
        """현재 위치에서 저장된 홈 좌표로 직접 복귀를 시작한다."""
        self._require_state(
            MissionState.FLYING,
            operation="start_return_home",
        )
        self._state = MissionState.RETURNING_HOME

    def complete_return_home(self, success: bool) -> None:
        """직접 홈 복귀 결과에 따라 기록과 상태를 갱신한다."""
        self._require_state(
            MissionState.RETURNING_HOME,
            operation="complete_return_home",
        )

        if success:
            # 직접 홈으로 이동하면 과거 경로는 현재 위치와 맞지 않으므로
            # 이후 Recall에서 사용되지 않도록 제거한다.
            self._action_history.clear()
            self._state = MissionState.FLYING
            return

        self._state = MissionState.ERROR

    def start_landing(self) -> None:
        """비행 상태에서 착륙을 시작한다."""
        self._require_state(
            MissionState.FLYING,
            operation="start_landing",
        )
        self._state = MissionState.LANDING

    def complete_landing(self, success: bool) -> None:
        """착륙 결과에 따라 대기 또는 오류 상태로 전환한다."""
        self._require_state(
            MissionState.LANDING,
            operation="complete_landing",
        )

        if success:
            # 착륙한 임무의 이동 기록이 다음 비행에 섞이지 않도록 한다.
            self._action_history.clear()
            self._state = MissionState.IDLE
            return

        self._state = MissionState.ERROR

    def emergency_stop(self) -> None:
        """현재 상태와 관계없이 긴급 정지 상태로 전환한다."""
        # 실행 중이던 명령은 완료되지 않았으므로 기록하지 않는다.
        self._current_action = None
        self._state = MissionState.EMERGENCY_STOPPED

    def _require_state(
        self,
        expected_state: MissionState,
        operation: str,
    ) -> None:
        """현재 상태가 요청한 동작의 시작 조건인지 확인한다."""
        if self._state is expected_state:
            return

        raise InvalidStateTransitionError(
            f"{operation} requires state {expected_state.value}, "
            f"but current state is {self._state.value}"
        )
