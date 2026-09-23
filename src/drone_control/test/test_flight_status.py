"""PX4 어댑터의 실제 비행 상태 알림을 검증한다."""

from types import SimpleNamespace
from unittest.mock import Mock

from px4_msgs.msg import VehicleStatus
from std_msgs.msg import String

from drone_control.px4_command_adapter import AdapterState
from drone_control.px4_command_adapter import Px4CommandAdapter
from drone_control.px4_command_adapter import TARGET_MODE_TAKEOFF
from drone_control.recall_runtime import RecallRuntime


def make_adapter_stub() -> SimpleNamespace:
    """ROS 네트워크 없이 상태 전환을 확인할 어댑터를 만든다."""
    logger = Mock()
    return SimpleNamespace(
        get_logger=lambda: logger,
        _publish_flight_status=Mock(),
    )


def test_flight_status_is_published_without_duplicate_log() -> None:
    """상태 메시지는 발행하되 기존 ROS 로그를 중복하지 않는다."""
    adapter = make_adapter_stub()
    adapter._flight_status_publisher = Mock()

    Px4CommandAdapter._publish_flight_status(adapter, "이륙 중")

    published = adapter._flight_status_publisher.publish.call_args.args[0]
    assert isinstance(published, String)
    assert published.data == "이륙 중"
    adapter.get_logger().info.assert_not_called()


def test_takeoff_completion_reports_holding() -> None:
    """목표 고도 확인 후에만 호버링 상태를 알린다."""
    adapter = make_adapter_stub()
    adapter._state = AdapterState.TAKING_OFF
    adapter._target_mode = TARGET_MODE_TAKEOFF
    adapter._is_offboard_and_armed = lambda: True
    adapter._has_reached_takeoff_altitude = lambda: True

    Px4CommandAdapter._handle_takeoff(adapter)

    assert adapter._state is AdapterState.HOLDING
    adapter._publish_flight_status.assert_called_once_with(
        "목표 고도 도달: 호버링 중"
    )


def test_landing_completion_reports_disarm() -> None:
    """시동 해제를 확인한 뒤 착륙 완료를 알린다."""
    adapter = make_adapter_stub()
    status = VehicleStatus()
    status.arming_state = VehicleStatus.ARMING_STATE_DISARMED
    adapter._vehicle_status = status
    adapter._state = AdapterState.LANDING
    adapter._target_position = (0.0, 0.0, -2.0)
    adapter._mission_target_position = (0.0, 0.0, -2.0)
    adapter._coordinate_calculator = Mock()
    adapter._command_retry_counter = 1
    adapter._recall_runtime = RecallRuntime()
    adapter._pending_history_action = None

    Px4CommandAdapter._handle_landing(adapter)

    assert adapter._state is AdapterState.LANDED
    adapter._publish_flight_status.assert_called_once_with(
        "착륙 완료: 시동 해제 확인"
    )


def test_runtime_rotation_reports_started() -> None:
    """실제 상대회전 목표를 설정한 뒤 회전 중 상태를 알린다."""
    adapter = make_adapter_stub()
    adapter._state = AdapterState.HOLDING
    adapter._messages_are_fresh = lambda: True
    adapter._is_offboard_and_armed = lambda: True
    adapter._target_position = (0.0, 0.0, -2.0)
    position = SimpleNamespace(
        xy_valid=True,
        z_valid=True,
        x=0.0,
        y=0.0,
        z=-2.0,
        heading=0.0,
    )
    adapter._vehicle_local_position = position
    adapter._recall_runtime = RecallRuntime()
    adapter._pending_history_action = None

    Px4CommandAdapter.rotate_relative(adapter, 90.0, None)

    assert adapter._state is AdapterState.ROTATING
    adapter._publish_flight_status.assert_called_once_with(
        "회전 중: 목표 방향으로 기수 변경"
    )
