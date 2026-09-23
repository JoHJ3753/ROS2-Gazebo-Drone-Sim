"""실행 이력을 이용한 Recall 순차 실행 상태를 관리한다."""

from collections import deque

from drone_control.action_history import ActionHistory
from drone_control.action_history import Command
from drone_control.reverse_executor import ReverseExecutor


class RecallRuntimeError(RuntimeError):
    """Recall 실행 상태가 올바르지 않을 때 발생한다."""


class RecallRuntime:
    """역추적 계획을 만들고 한 번에 한 명령씩 제공한다."""

    def __init__(
        self,
        action_history: ActionHistory | None = None,
        reverse_executor: ReverseExecutor | None = None,
    ) -> None:
        """실행 이력과 역방향 명령 생성기를 연결한다."""
        self._action_history = action_history or ActionHistory()
        self._reverse_executor = reverse_executor or ReverseExecutor()
        self._pending_commands: deque[Command] = deque()
        self._active = False

    @property
    def active(self) -> bool:
        """현재 Recall 계획을 실행 중인지 반환한다."""
        return self._active

    @property
    def remaining_count(self) -> int:
        """현재 단계 이후 남아 있는 명령 수를 반환한다."""
        return len(self._pending_commands)

    def record_completed_action(self, command: Command) -> None:
        """정상 비행 중 성공한 이동 또는 회전 명령을 저장한다."""
        if self._active:
            raise RecallRuntimeError(
                "Recall commands must not be added to Action History"
            )
        self._action_history.record(command)

    def start(self) -> Command:
        """저장된 이력으로 역추적을 시작하고 첫 명령을 반환한다."""
        if self._active:
            raise RecallRuntimeError("Recall is already in progress")
        if self._action_history.is_empty():
            raise RecallRuntimeError(
                "Cannot start recall because Action History is empty"
            )

        reverse_plan = self._reverse_executor.build_reverse_plan(
            self._action_history.get_actions()
        )
        self._pending_commands = deque(reverse_plan)
        self._active = True
        return self._pop_next_command()

    def complete_step(self) -> Command | None:
        """현재 단계 완료 후 다음 명령 또는 전체 완료를 반환한다."""
        if not self._active:
            raise RecallRuntimeError("Recall is not in progress")
        if self._pending_commands:
            return self._pop_next_command()

        self._active = False
        self._action_history.clear()
        return None

    def abort(self) -> None:
        """실행을 중단하고 현재 위치와 맞지 않는 이력을 제거한다."""
        self._pending_commands.clear()
        self._active = False
        # Recall 단계가 일부 수행된 뒤에는 원래 이력이 현재 위치를
        # 나타내지 않는다. 잘못된 재시도로 경로를 이탈하지 않도록
        # 전체 이력을 무효화한다.
        self._action_history.clear()

    def clear_history(self) -> None:
        """새 임무 시작 또는 직접 복귀 완료 후 이력을 제거한다."""
        self.abort()

    def get_history(self) -> list[Command]:
        """진단과 테스트를 위해 저장된 이력의 복사본을 반환한다."""
        return self._action_history.get_actions()

    def _pop_next_command(self) -> Command:
        """다음 역추적 명령을 큐에서 꺼낸다."""
        try:
            return self._pending_commands.popleft()
        except IndexError as error:
            self._active = False
            raise RecallRuntimeError(
                "Recall reverse plan is unexpectedly empty"
            ) from error
