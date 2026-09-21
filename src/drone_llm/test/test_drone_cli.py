"""대화형 CLI의 상태 표시를 검증한다."""

from types import SimpleNamespace

from std_msgs.msg import String

from drone_llm.drone_cli import DroneCli

from drone_llm.drone_cli import STATUS_TIMEOUT_SECONDS


def test_status_timeout_covers_initial_cpu_inference() -> None:
    """첫 CPU 추론이 길어져도 CLI가 결과를 기다린다."""
    assert STATUS_TIMEOUT_SECONDS == 300.0


def test_flight_status_is_printed(capsys) -> None:
    """PX4 어댑터 상태를 명령 입력 터미널에 출력한다."""
    message = String()
    message.data = "목표 고도 도달: 호버링 중"

    DroneCli._handle_flight_status(SimpleNamespace(), message)

    assert "[드론 상태] 목표 고도 도달: 호버링 중" in (
        capsys.readouterr().out
    )
