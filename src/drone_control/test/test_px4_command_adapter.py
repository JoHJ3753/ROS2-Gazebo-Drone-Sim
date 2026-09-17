"""PX4 명령 어댑터의 좌표 계산과 상태 판정을 검증한다."""

import pytest

from px4_msgs.msg import VehicleLocalPosition
from px4_msgs.msg import VehicleStatus

from drone_control.px4_command_adapter import calculate_takeoff_target
from drone_control.px4_command_adapter import has_reached_altitude
from drone_control.px4_command_adapter import has_reached_position
from drone_control.px4_command_adapter import is_offboard_and_armed
from drone_control.px4_command_adapter import is_vehicle_ready


def make_valid_position() -> VehicleLocalPosition:
    """제어에 사용할 수 있는 유효한 로컬 위치를 생성한다."""
    position = VehicleLocalPosition()
    position.xy_valid = True
    position.z_valid = True
    position.x = 1.5
    position.y = -2.0
    position.z = -0.3
    return position


def make_ready_status() -> VehicleStatus:
    """이륙 전 검사를 통과한 기체 상태를 생성한다."""
    status = VehicleStatus()
    status.pre_flight_checks_pass = True
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
