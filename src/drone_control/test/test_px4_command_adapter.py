"""PX4 명령 어댑터의 좌표 계산과 상태 판정을 검증한다."""

import math
import pytest

from px4_msgs.msg import VehicleLocalPosition
from px4_msgs.msg import VehicleStatus

from drone_control.px4_command_adapter import calculate_takeoff_target
from drone_control.px4_command_adapter import has_reached_altitude
from drone_control.px4_command_adapter import has_reached_position
from drone_control.px4_command_adapter import is_offboard_and_armed
from drone_control.px4_command_adapter import is_vehicle_speed_stable
from drone_control.px4_command_adapter import is_vehicle_takeoff_eligible
from drone_control.px4_command_adapter import is_vehicle_disarmed
from drone_control.px4_command_adapter import is_vehicle_ready
from drone_control.px4_command_adapter import validate_target_mode
from drone_control.px4_command_adapter import AdapterState
from drone_control.px4_command_adapter import Px4CommandAdapter
from drone_control.px4_command_adapter import TARGET_MODE_RELATIVE
from drone_control.px4_command_adapter import TARGET_MODE_ROTATION
from drone_control.px4_command_adapter import (
    TAKEOFF_STABILITY_REQUIRED_TICKS,
)


def make_valid_position() -> VehicleLocalPosition:
    """제어에 사용할 수 있는 안정적인 로컬 위치를 생성한다."""
    position = VehicleLocalPosition()
    position.xy_valid = True
    position.z_valid = True
    position.v_xy_valid = True
    position.v_z_valid = True
    position.heading_good_for_control = True
    position.x = 1.5
    position.y = -2.0
    position.z = -0.3
    position.vx = 0.0
    position.vy = 0.0
    position.vz = 0.0
    position.heading = 0.0
    return position


def make_ready_status() -> VehicleStatus:
    """안전하게 자동 제어를 시작할 수 있는 상태를 생성한다."""
    status = VehicleStatus()
    status.arming_state = VehicleStatus.ARMING_STATE_DISARMED
    status.failsafe = False
    status.pre_flight_checks_pass = True
    status.armed_time = 0
    status.takeoff_time = 0
    return status


def test_takeoff_target_preserves_horizontal_position():
    """수직 이륙 목표가 현재 x와 y 위치를 유지하는지 확인한다."""
    target = calculate_takeoff_target(
        current_x_m=1.5,
        current_y_m=-2.0,
        current_z_m=-0.3,
        height_m=2.0,
    )

    assert target[0] == pytest.approx(1.5)
    assert target[1] == pytest.approx(-2.0)


def test_takeoff_target_decreases_ned_z():
    """NED 좌표에서 상승 목표가 현재 z보다 작아지는지 확인한다."""
    target = calculate_takeoff_target(
        current_x_m=1.5,
        current_y_m=-2.0,
        current_z_m=-0.3,
        height_m=2.0,
    )

    assert target[2] == pytest.approx(-2.3)


@pytest.mark.parametrize(
    "height_m",
    [
        0.0,
        -1.0,
    ],
)
def test_takeoff_target_rejects_non_positive_height(height_m):
    """0 이하의 이륙 높이를 거부하는지 확인한다."""
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        calculate_takeoff_target(
            current_x_m=0.0,
            current_y_m=0.0,
            current_z_m=0.0,
            height_m=height_m,
        )


@pytest.mark.parametrize(
    ("position", "status"),
    [
        (None, make_ready_status()),
        (make_valid_position(), None),
    ],
)
def test_vehicle_is_not_ready_without_required_data(
    position,
    status,
):
    """위치 또는 상태 메시지가 없으면 준비되지 않은 것으로 판정한다."""
    assert not is_vehicle_ready(position, status)


@pytest.mark.parametrize(
    ("xy_valid", "z_valid"),
    [
        (False, True),
        (True, False),
        (False, False),
    ],
)
def test_vehicle_is_not_ready_with_invalid_position(
    xy_valid,
    z_valid,
):
    """수평 또는 수직 위치가 유효하지 않으면 이륙을 차단한다."""
    position = make_valid_position()
    position.xy_valid = xy_valid
    position.z_valid = z_valid

    assert not is_vehicle_ready(
        position,
        make_ready_status(),
    )


def test_vehicle_is_not_ready_when_preflight_check_fails():
    """PX4 이륙 전 검사를 통과하지 못하면 이륙을 차단한다."""
    status = make_ready_status()
    status.pre_flight_checks_pass = False

    assert not is_vehicle_ready(
        make_valid_position(),
        status,
    )


def test_vehicle_is_ready_with_valid_position_and_preflight():
    """유효한 위치와 이륙 전 검사 결과가 있으면 준비 상태가 된다."""
    assert is_vehicle_ready(
        make_valid_position(),
        make_ready_status(),
    )


@pytest.mark.parametrize(
    ("current_z_m", "expected"),
    [
        (-2.30, True),
        (-2.15, True),
        (-2.45, True),
        (-2.14, False),
        (-2.46, False),
    ],
)
def test_altitude_reached_uses_tolerance(
    current_z_m,
    expected,
):
    """목표 고도의 위아래 허용 오차를 동일하게 적용한다."""
    result = has_reached_altitude(
        current_z_m=current_z_m,
        target_z_m=-2.30,
        tolerance_m=0.15,
    )

    assert result is expected


def test_altitude_reached_rejects_negative_tolerance():
    """음수 고도 허용 오차를 거부하는지 확인한다."""
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        has_reached_altitude(
            current_z_m=-2.3,
            target_z_m=-2.3,
            tolerance_m=-0.1,
        )


@pytest.mark.parametrize(
    ("current_position", "expected"),
    [
        # 목표 좌표와 완전히 같으면 도달한 상태다.
        ((1.0, 2.0, -2.0), True),

        # 목표에서 0.2m 떨어진 경계값까지 허용한다.
        ((1.2, 2.0, -2.0), True),

        # 세 축 오차의 직선거리가 0.2m 이내면 허용한다.
        ((1.1, 2.1, -1.9), True),

        # 한 축이라도 허용 거리보다 멀면 도달하지 않은 상태다.
        ((1.21, 2.0, -2.0), False),

        # 각 축의 오차가 작더라도 합산한 직선거리가 크면 거부한다.
        ((1.15, 2.15, -1.85), False),
    ],
)
def test_position_reached_uses_three_dimensional_distance(
    current_position,
    expected,
):
    """NED 세 축의 직선거리로 목표 위치 도달 여부를 판단한다."""
    result = has_reached_position(
        current_position=current_position,
        target_position=(1.0, 2.0, -2.0),
        tolerance_m=0.2,
    )

    assert result is expected


def test_position_reached_rejects_negative_tolerance():
    """음수 위치 허용 오차를 거부하는지 확인한다."""
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        has_reached_position(
            current_position=(0.0, 0.0, 0.0),
            target_position=(1.0, 0.0, -2.0),
            tolerance_m=-0.1,
        )


@pytest.mark.parametrize(
    ("nav_state", "arming_state", "expected"),
    [
        (
            VehicleStatus.NAVIGATION_STATE_OFFBOARD,
            VehicleStatus.ARMING_STATE_ARMED,
            True,
        ),
        (
            VehicleStatus.NAVIGATION_STATE_AUTO_LOITER,
            VehicleStatus.ARMING_STATE_ARMED,
            False,
        ),
        (
            VehicleStatus.NAVIGATION_STATE_OFFBOARD,
            VehicleStatus.ARMING_STATE_DISARMED,
            False,
        ),
    ],
)
def test_offboard_and_armed_requires_both_states(
    nav_state,
    arming_state,
    expected,
):
    """Offboard 모드와 시동 상태를 모두 만족해야 하는지 확인한다."""
    status = VehicleStatus()
    status.nav_state = nav_state
    status.arming_state = arming_state

    assert is_offboard_and_armed(status) is expected


def test_offboard_and_armed_rejects_missing_status():
    """기체 상태 메시지가 없으면 비행 가능 상태가 아니다."""
    assert not is_offboard_and_armed(None)


@pytest.mark.parametrize(
    ("arming_state", "expected"),
    [
        (
            VehicleStatus.ARMING_STATE_DISARMED,
            True,
        ),
        (
            VehicleStatus.ARMING_STATE_ARMED,
            False,
        ),
    ],
)
def test_vehicle_disarmed_uses_arming_state(
    arming_state,
    expected,
):
    """PX4 시동 상태를 이용해 착륙 완료 여부를 판정한다."""
    status = VehicleStatus()
    status.arming_state = arming_state

    assert is_vehicle_disarmed(status) is expected


def test_vehicle_disarmed_rejects_missing_status():
    """PX4 상태 메시지가 없으면 시동 해제로 판정하지 않는다."""
    assert not is_vehicle_disarmed(None)

# ============================================================
# 목표좌표 계산 모드 검사
# ============================================================


@pytest.mark.parametrize(
    "target_mode",
    [
        "takeoff",
        "absolute",
        "relative",
        "rotation",
    ],
)
def test_validate_target_mode_accepts_supported_modes(target_mode):
    """지원하는 목표좌표 계산 모드는 그대로 반환하는지 확인한다."""
    assert validate_target_mode(target_mode) == target_mode


@pytest.mark.parametrize(
    "target_mode",
    [
        "",
        "body",
        "global",
        "forward",
        None,
        1,
    ],
)
def test_validate_target_mode_rejects_unsupported_modes(target_mode):
    """지원하지 않는 목표좌표 계산 모드를 거부하는지 확인한다."""
    with pytest.raises(ValueError):
        validate_target_mode(target_mode)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("arming_state", VehicleStatus.ARMING_STATE_ARMED),
        ("failsafe", True),
        ("pre_flight_checks_pass", False),
        ("armed_time", 1),
        ("takeoff_time", 1),
    ],
)
def test_vehicle_is_not_ready_with_unsafe_status(
    field_name,
    field_value,
):
    """비행 이력이나 위험 상태가 있으면 시작을 거부한다."""
    status = make_ready_status()
    setattr(status, field_name, field_value)

    assert not is_vehicle_ready(
        make_valid_position(),
        status,
    )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("v_xy_valid", False),
        ("v_z_valid", False),
        ("vx", 0.16),
        ("vy", 0.16),
        ("vz", 0.11),
        ("heading", float("nan")),
    ],
)
def test_vehicle_is_not_ready_with_unstable_position(
    field_name,
    field_value,
):
    """속도나 방향 추정이 불안정하면 시작을 거부한다."""
    position = make_valid_position()
    setattr(position, field_name, field_value)

    assert not is_vehicle_ready(
        position,
        make_ready_status(),
    )


def test_vehicle_ready_does_not_depend_on_heading_good_flag():
    """유한한 heading은 노드의 연속 안정성 검사에서 판정한다."""
    position = make_valid_position()
    position.heading_good_for_control = False

    assert is_vehicle_ready(
        position,
        make_ready_status(),
    )


def test_takeoff_eligibility_allows_transient_speed_noise():
    """기본 안전 상태는 순간적인 속도 초과와 별도로 판정한다."""
    position = make_valid_position()
    position.vz = 0.11
    status = make_ready_status()

    assert is_vehicle_takeoff_eligible(position, status)
    assert not is_vehicle_speed_stable(position)
    assert not is_vehicle_ready(position, status)


@pytest.mark.parametrize(
    ("vx", "vy", "vz", "expected"),
    [
        (0.0, 0.0, 0.0, True),
        (0.15, 0.0, 0.10, True),
        (0.16, 0.0, 0.0, False),
        (0.0, 0.0, 0.11, False),
    ],
)
def test_vehicle_speed_stability_uses_configured_limits(
    vx,
    vy,
    vz,
    expected,
):
    """수평 및 수직 속도 임계값을 독립적으로 적용한다."""
    position = make_valid_position()
    position.vx = vx
    position.vy = vy
    position.vz = vz

    assert is_vehicle_speed_stable(position) is expected


class FakeLogger:
    """런타임 이동 테스트에서 로그 호출을 기록한다."""

    def __init__(self):
        """기록할 로그 목록을 생성한다."""
        self.messages = []

    def info(self, message):
        """정보 로그를 저장한다."""
        self.messages.append(message)

    def warning(self, message):
        """경고 로그를 저장한다."""
        self.messages.append(message)


class RuntimeMoveAdapterStub:
    """ROS 노드 없이 런타임 상대이동 메서드를 검사한다."""

    def __init__(self):
        """정상적인 호버링 상태와 위치 데이터를 준비한다."""
        self._state = AdapterState.HOLDING
        self._vehicle_local_position = make_valid_position()
        self._target_mode = None
        self._relative_direction = None
        self._relative_distance_m = None
        self._relative_yaw_deg = None
        self._target_yaw_rad = 0.0
        self._target_position = (
            1.5,
            -2.0,
            -0.3,
        )
        self._hover_deadline_monotonic = None
        self._vehicle_status = make_ready_status()
        self._pending_takeoff_altitude_m = None
        self._takeoff_stability_counter = 0
        self._takeoff_stability_deadline_monotonic = None
        self._mission_target_position = None
        self._coordinate_calculator = None
        self._setpoint_stream_counter = 0
        self._command_retry_counter = 0
        self.flight_statuses: list[str] = []
        self.messages_fresh = True
        self.offboard_and_armed = True
        self.logger = FakeLogger()

    def _messages_are_fresh(self):
        return self.messages_fresh

    def _is_offboard_and_armed(self):
        return self.offboard_and_armed

    def _publish_flight_status(self, status: str) -> None:
        """실제 ROS 발행 대신 상태 알림을 기록한다."""
        self.flight_statuses.append(status)

    def _prepare_takeoff_target(self, height_m):
        """실제 어댑터의 이륙 목표 계산을 호출한다."""
        Px4CommandAdapter._prepare_takeoff_target(
            self,
            height_m,
        )

    def get_logger(self):
        """테스트용 로거를 반환한다."""
        return self.logger


def test_runtime_move_prepares_body_relative_target():
    """호버링 중 기수 기준 상대이동 목표를 준비한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._vehicle_local_position.heading = 0.0

    Px4CommandAdapter.move_drone(
        adapter,
        direction="forward",
        distance_m=2.0,
        speed_mps=None,
    )

    assert adapter._target_mode == TARGET_MODE_RELATIVE
    assert adapter._relative_direction == "forward"
    assert adapter._relative_distance_m == pytest.approx(2.0)
    assert adapter._target_position == pytest.approx(
        (
            3.5,
            -2.0,
            -0.3,
        )
    )
    assert adapter._state is AdapterState.MOVING_TO_TARGET
    assert adapter.flight_statuses == ["이동 중: 목표 위치로 비행"]


def test_runtime_move_rejects_command_outside_holding_state():
    """호버링 상태가 아니면 런타임 이동을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.MOVING_TO_TARGET

    with pytest.raises(
        RuntimeError,
        match="requires the adapter to be holding",
    ):
        Px4CommandAdapter.move_drone(
            adapter,
            direction="forward",
            distance_m=1.0,
            speed_mps=None,
        )


def test_runtime_move_rejects_stale_vehicle_data():
    """PX4 데이터가 오래됐으면 런타임 이동을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.messages_fresh = False

    with pytest.raises(
        RuntimeError,
        match="message is stale",
    ):
        Px4CommandAdapter.move_drone(
            adapter,
            direction="forward",
            distance_m=1.0,
            speed_mps=None,
        )


def test_runtime_move_requires_armed_offboard_vehicle():
    """Armed 및 Offboard 상태가 아니면 이동을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.offboard_and_armed = False

    with pytest.raises(
        RuntimeError,
        match="armed Offboard vehicle",
    ):
        Px4CommandAdapter.move_drone(
            adapter,
            direction="forward",
            distance_m=1.0,
            speed_mps=None,
        )


def test_runtime_move_rejects_speed_until_supported():
    """속도 제어가 구현되기 전에는 speed_mps를 거부한다."""
    adapter = RuntimeMoveAdapterStub()

    with pytest.raises(
        RuntimeError,
        match="speed control is not implemented",
    ):
        Px4CommandAdapter.move_drone(
            adapter,
            direction="forward",
            distance_m=1.0,
            speed_mps=0.5,
        )


def test_runtime_horizontal_move_preserves_holding_altitude():
    """수평 이동 중에는 기존 호버링 목표 고도를 유지한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._vehicle_local_position.z = -0.1

    Px4CommandAdapter.move_drone(
        adapter,
        direction="forward",
        distance_m=1.0,
        speed_mps=None,
    )

    assert adapter._target_position[2] == pytest.approx(-0.3)


def test_runtime_vertical_move_preserves_holding_xy_target():
    """수직 이동 중에는 기존 호버링 수평 목표를 유지한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._vehicle_local_position.x = 1.7
    adapter._vehicle_local_position.y = -1.8

    Px4CommandAdapter.move_drone(
        adapter,
        direction="up",
        distance_m=1.0,
        speed_mps=None,
    )

    assert adapter._target_position == pytest.approx(
        (
            1.5,
            -2.0,
            -1.3,
        )
    )


def test_runtime_rotation_prepares_relative_yaw_target():
    """호버링 중 현재 기수 기준 상대회전 목표를 준비한다."""
    adapter = RuntimeMoveAdapterStub()
    original_position_target = adapter._target_position
    adapter._vehicle_local_position.heading = 0.0

    Px4CommandAdapter.rotate_relative(
        adapter,
        yaw_deg=90.0,
        yaw_speed_dps=None,
    )

    assert adapter._target_mode == TARGET_MODE_ROTATION
    assert adapter._relative_yaw_deg == pytest.approx(90.0)
    assert adapter._target_yaw_rad == pytest.approx(math.pi / 2.0)
    assert adapter._target_position == original_position_target
    assert adapter._state is AdapterState.ROTATING
    assert adapter.flight_statuses == ["회전 중: 목표 방향으로 기수 변경"]


def test_runtime_rotation_rejects_command_outside_holding_state():
    """호버링 상태가 아니면 런타임 회전을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.ROTATING

    with pytest.raises(
        RuntimeError,
        match="requires the adapter to be holding",
    ):
        Px4CommandAdapter.rotate_relative(
            adapter,
            yaw_deg=90.0,
            yaw_speed_dps=None,
        )


def test_runtime_rotation_rejects_stale_vehicle_data():
    """PX4 데이터가 오래됐으면 런타임 회전을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.messages_fresh = False

    with pytest.raises(
        RuntimeError,
        match="message is stale",
    ):
        Px4CommandAdapter.rotate_relative(
            adapter,
            yaw_deg=90.0,
            yaw_speed_dps=None,
        )


def test_runtime_rotation_requires_armed_offboard_vehicle():
    """Armed 및 Offboard 상태가 아니면 회전을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.offboard_and_armed = False

    with pytest.raises(
        RuntimeError,
        match="armed Offboard vehicle",
    ):
        Px4CommandAdapter.rotate_relative(
            adapter,
            yaw_deg=90.0,
            yaw_speed_dps=None,
        )


def test_runtime_rotation_rejects_speed_until_supported():
    """속도 제어 구현 전에는 yaw_speed_dps를 거부한다."""
    adapter = RuntimeMoveAdapterStub()

    with pytest.raises(
        RuntimeError,
        match="speed control is not implemented",
    ):
        Px4CommandAdapter.rotate_relative(
            adapter,
            yaw_deg=90.0,
            yaw_speed_dps=30.0,
        )


def test_runtime_rotation_rejects_invalid_heading():
    """유효하지 않은 PX4 heading으로 목표를 만들지 않는다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._vehicle_local_position.heading = float("nan")

    with pytest.raises(
        RuntimeError,
        match="Failed to calculate runtime yaw target",
    ):
        Px4CommandAdapter.rotate_relative(
            adapter,
            yaw_deg=90.0,
            yaw_speed_dps=None,
        )


def test_runtime_hover_without_duration_keeps_holding_state():
    """시간을 생략한 호버링은 다음 명령까지 유지한다."""
    adapter = RuntimeMoveAdapterStub()
    original_target = adapter._target_position

    Px4CommandAdapter.hover(
        adapter,
        duration_s=None,
    )

    assert adapter._state is AdapterState.HOLDING
    assert adapter._target_position == original_target
    assert adapter._hover_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "호버링 유지 중: 다음 명령 대기"
    ]


def test_runtime_timed_hover_sets_deadline(monkeypatch):
    """시간 지정 호버링은 종료 시각과 전용 상태를 설정한다."""
    adapter = RuntimeMoveAdapterStub()
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 100.0,
    )

    Px4CommandAdapter.hover(
        adapter,
        duration_s=3.0,
    )

    assert adapter._state is AdapterState.HOVERING
    assert adapter._hover_deadline_monotonic == pytest.approx(103.0)
    assert adapter.flight_statuses == [
        "호버링 중: 3.00초"
    ]


def test_runtime_timed_hover_waits_before_deadline(monkeypatch):
    """종료 시각 전에는 호버링 상태를 유지한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.HOVERING
    adapter._hover_deadline_monotonic = 103.0
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 102.9,
    )

    Px4CommandAdapter._handle_hovering(adapter)

    assert adapter._state is AdapterState.HOVERING
    assert adapter._hover_deadline_monotonic == pytest.approx(103.0)


def test_runtime_timed_hover_completes_at_deadline(monkeypatch):
    """종료 시각이 되면 다시 명령 대기 상태로 돌아간다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.HOVERING
    adapter._hover_deadline_monotonic = 103.0
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 103.0,
    )

    Px4CommandAdapter._handle_hovering(adapter)

    assert adapter._state is AdapterState.HOLDING
    assert adapter._hover_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "호버링 완료: 다음 명령 대기"
    ]


def test_runtime_hover_rejects_command_outside_holding_state():
    """명령 대기 상태가 아니면 호버링 명령을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.MOVING_TO_TARGET

    with pytest.raises(
        RuntimeError,
        match="requires the adapter to be holding",
    ):
        Px4CommandAdapter.hover(
            adapter,
            duration_s=3.0,
        )


def test_runtime_hover_rejects_stale_vehicle_data():
    """PX4 데이터가 오래됐으면 호버링 명령을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.messages_fresh = False

    with pytest.raises(
        RuntimeError,
        match="message is stale",
    ):
        Px4CommandAdapter.hover(
            adapter,
            duration_s=3.0,
        )


def test_runtime_hover_requires_armed_offboard_vehicle():
    """Armed 및 Offboard 상태가 아니면 호버링을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter.offboard_and_armed = False

    with pytest.raises(
        RuntimeError,
        match="armed Offboard vehicle",
    ):
        Px4CommandAdapter.hover(
            adapter,
            duration_s=3.0,
        )


@pytest.mark.parametrize(
    "active_state",
    [
        AdapterState.MOVING_TO_TARGET,
        AdapterState.ROTATING,
        AdapterState.HOVERING,
    ],
)
def test_runtime_cancel_holds_current_position(active_state):
    """취소 가능한 동작을 현재 위치와 기수에서 중단한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = active_state
    adapter._hover_deadline_monotonic = 200.0
    adapter._vehicle_local_position.x = 2.5
    adapter._vehicle_local_position.y = -1.25
    adapter._vehicle_local_position.z = -1.75
    adapter._vehicle_local_position.heading = 0.75

    Px4CommandAdapter.cancel(adapter)

    assert adapter._state is AdapterState.HOLDING
    assert adapter._target_position == pytest.approx(
        (2.5, -1.25, -1.75)
    )
    assert adapter._target_yaw_rad == pytest.approx(0.75)
    assert adapter._hover_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "동작 취소 완료: 현재 위치에서 호버링"
    ]


@pytest.mark.parametrize(
    "inactive_state",
    [
        AdapterState.IDLE,
        AdapterState.HOLDING,
        AdapterState.LANDING,
    ],
)
def test_runtime_cancel_rejects_inactive_state(inactive_state):
    """취소할 동작이 없거나 착륙 중이면 취소 명령을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = inactive_state

    with pytest.raises(
        RuntimeError,
        match="requires active movement",
    ):
        Px4CommandAdapter.cancel(adapter)


def test_runtime_cancel_rejects_stale_vehicle_data():
    """PX4 데이터가 오래됐으면 취소 명령을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.MOVING_TO_TARGET
    adapter.messages_fresh = False

    with pytest.raises(
        RuntimeError,
        match="message is stale",
    ):
        Px4CommandAdapter.cancel(adapter)


def test_runtime_cancel_requires_armed_offboard_vehicle():
    """Armed 및 Offboard 상태가 아니면 취소 명령을 거부한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.ROTATING
    adapter.offboard_and_armed = False

    with pytest.raises(
        RuntimeError,
        match="armed Offboard vehicle",
    ):
        Px4CommandAdapter.cancel(adapter)


def test_runtime_cancel_rejects_invalid_position():
    """유효하지 않은 현재 위치로 정지 목표를 생성하지 않는다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.MOVING_TO_TARGET
    adapter._vehicle_local_position.z = float("nan")

    with pytest.raises(
        RuntimeError,
        match="not valid for cancellation",
    ):
        Px4CommandAdapter.cancel(adapter)


def test_runtime_takeoff_waits_for_stable_speed(monkeypatch):
    """이륙 명령은 순간 속도 초과 시 거부되지 않고 대기한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.IDLE
    adapter._vehicle_local_position.vz = 0.11
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 100.0,
    )

    Px4CommandAdapter.takeoff(
        adapter,
        altitude_m=2.0,
    )

    assert (
        adapter._state
        is AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    )
    assert adapter._pending_takeoff_altitude_m == pytest.approx(2.0)
    assert adapter._takeoff_stability_counter == 0
    assert (
        adapter._takeoff_stability_deadline_monotonic
        == pytest.approx(115.0)
    )
    assert adapter.flight_statuses == [
        "이륙 대기 중: 속도 안정화 확인"
    ]


def test_takeoff_stability_wait_resets_on_unstable_sample(monkeypatch):
    """불안정한 속도 표본이 들어오면 연속 카운트를 초기화한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    adapter._pending_takeoff_altitude_m = 2.0
    adapter._takeoff_stability_counter = 5
    adapter._takeoff_stability_deadline_monotonic = 115.0
    adapter._vehicle_local_position.vz = 0.11
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 101.0,
    )

    Px4CommandAdapter._handle_takeoff_stability_wait(adapter)

    assert (
        adapter._state
        is AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    )
    assert adapter._takeoff_stability_counter == 0


def test_takeoff_starts_after_consecutive_stable_samples(monkeypatch):
    """필요한 연속 안정 표본이 모이면 이륙 세트포인트를 시작한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    adapter._pending_takeoff_altitude_m = 2.0
    adapter._takeoff_stability_counter = (
        TAKEOFF_STABILITY_REQUIRED_TICKS - 1
    )
    adapter._takeoff_stability_deadline_monotonic = 115.0
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 101.0,
    )

    Px4CommandAdapter._handle_takeoff_stability_wait(adapter)

    assert adapter._state is AdapterState.STREAMING_SETPOINTS
    assert adapter._target_mode == "takeoff"
    assert adapter._target_position == pytest.approx(
        (1.5, -2.0, -2.3)
    )
    assert adapter._pending_takeoff_altitude_m is None
    assert adapter._takeoff_stability_counter == 0
    assert adapter._takeoff_stability_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "이륙 준비 중: 목표 고도 2.00m"
    ]


def test_takeoff_stability_wait_times_out(monkeypatch):
    """제한 시간 안에 안정되지 않으면 이륙 요청을 안전하게 취소한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    adapter._pending_takeoff_altitude_m = 2.0
    adapter._takeoff_stability_counter = 3
    adapter._takeoff_stability_deadline_monotonic = 115.0
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 115.0,
    )

    Px4CommandAdapter._handle_takeoff_stability_wait(adapter)

    assert adapter._state is AdapterState.IDLE
    assert adapter._pending_takeoff_altitude_m is None
    assert adapter._takeoff_stability_counter == 0
    assert adapter._takeoff_stability_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "이륙 취소: 기체 상태 안정화 시간 초과"
    ]


def test_runtime_cancel_clears_pending_takeoff():
    """속도 안정화 대기 중인 이륙 요청도 취소할 수 있다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    adapter._pending_takeoff_altitude_m = 2.0
    adapter._takeoff_stability_counter = 4
    adapter._takeoff_stability_deadline_monotonic = 115.0

    Px4CommandAdapter.cancel(adapter)

    assert adapter._state is AdapterState.IDLE
    assert adapter._pending_takeoff_altitude_m is None
    assert adapter._takeoff_stability_counter == 0
    assert adapter._takeoff_stability_deadline_monotonic is None
    assert adapter.flight_statuses == [
        "이륙 대기 취소: 다음 명령 대기"
    ]


def test_adapter_vehicle_ready_wrapper_uses_current_messages():
    """어댑터 준비 상태 래퍼가 현재 PX4 메시지를 사용한다."""
    adapter = RuntimeMoveAdapterStub()

    assert Px4CommandAdapter._is_vehicle_ready(adapter)


def test_takeoff_wait_tolerates_transient_ineligible_state(monkeypatch):
    """순간적인 준비 상태 해제는 요청 취소 대신 카운트만 초기화한다."""
    adapter = RuntimeMoveAdapterStub()
    adapter._state = AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    adapter._pending_takeoff_altitude_m = 2.0
    adapter._takeoff_stability_counter = 5
    adapter._takeoff_stability_deadline_monotonic = 115.0
    adapter._vehicle_status.pre_flight_checks_pass = False
    monkeypatch.setattr(
        "drone_control.px4_command_adapter.time.monotonic",
        lambda: 101.0,
    )

    Px4CommandAdapter._handle_takeoff_stability_wait(adapter)

    assert (
        adapter._state
        is AdapterState.WAITING_FOR_TAKEOFF_STABILITY
    )
    assert adapter._pending_takeoff_altitude_m == pytest.approx(2.0)
    assert adapter._takeoff_stability_counter == 0
    assert (
        adapter._takeoff_stability_deadline_monotonic
        == pytest.approx(115.0)
    )
    assert adapter.flight_statuses == []
