"""홈 기준 절대좌표를 PX4 NED 좌표로 변환하는 기능을 검증한다."""

import math

import pytest

from drone_control.coordinate_calculator import (
    CoordinateCalculationError,
)
from drone_control.coordinate_calculator import CoordinateCalculator
from drone_control.coordinate_calculator import NedPosition


def make_home_position() -> NedPosition:
    """테스트에서 사용할 PX4 홈 위치를 생성한다."""
    return NedPosition(
        north_m=1.0,
        east_m=-2.0,
        down_m=-0.3,
    )


def test_home_position_is_preserved():
    """계산기에 전달한 홈 위치가 그대로 보존되는지 확인한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    assert calculator.home_position == make_home_position()


def test_zero_absolute_target_returns_home_position():
    """모든 홈 기준 좌표가 0이면 PX4 홈 위치를 반환한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_absolute_target(
        north_m=0.0,
        east_m=0.0,
        altitude_m=0.0,
    )

    assert target == make_home_position()


def test_absolute_target_adds_north_and_east_offsets():
    """북쪽과 동쪽 좌표가 PX4 홈 위치에 더해지는지 확인한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_absolute_target(
        north_m=2.0,
        east_m=3.0,
        altitude_m=0.0,
    )

    assert target.north_m == pytest.approx(3.0)
    assert target.east_m == pytest.approx(1.0)
    assert target.down_m == pytest.approx(-0.3)


def test_absolute_target_converts_altitude_to_ned_down():
    """양수 고도가 PX4 NED의 음수 Z 방향으로 변환되는지 확인한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_absolute_target(
        north_m=0.0,
        east_m=0.0,
        altitude_m=2.0,
    )

    # 홈의 down=-0.3에서 위로 2m 이동하면 목표 down은 -2.3이다.
    assert target.down_m == pytest.approx(-2.3)


def test_negative_north_and_east_coordinates_are_allowed():
    """남쪽과 서쪽 좌표를 음수 값으로 표현할 수 있는지 확인한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_absolute_target(
        north_m=-2.0,
        east_m=-3.0,
        altitude_m=1.0,
    )

    assert target.north_m == pytest.approx(-1.0)
    assert target.east_m == pytest.approx(-5.0)
    assert target.down_m == pytest.approx(-1.3)


def test_px4_tuple_uses_north_east_down_order():
    """PX4 목표 좌표가 x, y, z에 맞는 NED 순서인지 확인한다."""
    position = NedPosition(
        north_m=1.0,
        east_m=2.0,
        down_m=-3.0,
    )

    assert position.as_px4_tuple() == (
        1.0,
        2.0,
        -3.0,
    )


def test_negative_altitude_is_rejected():
    """홈 아래를 의미하는 음수 고도 입력을 현재 단계에서 거부한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="cannot be negative",
    ):
        calculator.calculate_absolute_target(
            north_m=0.0,
            east_m=0.0,
            altitude_m=-1.0,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("north_m", math.nan),
        ("north_m", math.inf),
        ("east_m", -math.inf),
        ("altitude_m", math.nan),
    ],
)
def test_non_finite_target_value_is_rejected(
    field_name,
    invalid_value,
):
    """유한하지 않은 좌표가 PX4 목표로 전달되지 않게 한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )
    arguments = {
        "north_m": 0.0,
        "east_m": 0.0,
        "altitude_m": 2.0,
    }
    arguments[field_name] = invalid_value

    with pytest.raises(
        CoordinateCalculationError,
        match="must be a finite number",
    ):
        calculator.calculate_absolute_target(**arguments)


def test_non_finite_home_position_is_rejected():
    """유효하지 않은 홈 위치로 계산기를 생성하지 못하게 한다."""
    invalid_home = NedPosition(
        north_m=math.nan,
        east_m=0.0,
        down_m=0.0,
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="home_position.north_m",
    ):
        CoordinateCalculator(home_position=invalid_home)


def test_boolean_coordinate_is_rejected():
    """Boolean 값이 숫자 좌표로 처리되지 않게 한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="must be a finite number",
    ):
        calculator.calculate_absolute_target(
            north_m=True,
            east_m=0.0,
            altitude_m=2.0,
        )


def make_current_position() -> NedPosition:
    """상대이동 테스트에서 사용할 현재 NED 위치를 생성한다."""
    return NedPosition(
        north_m=10.0,
        east_m=20.0,
        down_m=-3.0,
    )


@pytest.mark.parametrize(
    (
        "direction",
        "expected_north_m",
        "expected_east_m",
    ),
    [
        ("forward", 12.0, 20.0),
        ("backward", 8.0, 20.0),
        ("right", 10.0, 22.0),
        ("left", 10.0, 18.0),
    ],
)
def test_relative_horizontal_move_when_heading_north(
    direction,
    expected_north_m,
    expected_east_m,
):
    """기수가 북쪽일 때 기체 기준 방향을 NED 좌표로 변환한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_relative_target(
        current_position=make_current_position(),
        heading_rad=0.0,
        direction=direction,
        distance_m=2.0,
    )

    assert target.north_m == pytest.approx(expected_north_m)
    assert target.east_m == pytest.approx(expected_east_m)
    assert target.down_m == pytest.approx(-3.0)


@pytest.mark.parametrize(
    (
        "direction",
        "expected_north_m",
        "expected_east_m",
    ),
    [
        ("forward", 10.0, 22.0),
        ("backward", 10.0, 18.0),
        ("right", 8.0, 20.0),
        ("left", 12.0, 20.0),
    ],
)
def test_relative_horizontal_move_when_heading_east(
    direction,
    expected_north_m,
    expected_east_m,
):
    """기수가 동쪽일 때 기체 기준 방향을 NED 좌표로 변환한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_relative_target(
        current_position=make_current_position(),
        heading_rad=math.pi / 2.0,
        direction=direction,
        distance_m=2.0,
    )

    assert target.north_m == pytest.approx(expected_north_m)
    assert target.east_m == pytest.approx(expected_east_m)
    assert target.down_m == pytest.approx(-3.0)


@pytest.mark.parametrize(
    ("direction", "expected_down_m"),
    [
        ("up", -5.0),
        ("down", -1.0),
    ],
)
def test_relative_vertical_move_changes_ned_down(
    direction,
    expected_down_m,
):
    """상승과 하강 명령이 NED Down 축으로 변환되는지 확인한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_relative_target(
        current_position=make_current_position(),
        heading_rad=0.0,
        direction=direction,
        distance_m=2.0,
    )

    assert target.north_m == pytest.approx(10.0)
    assert target.east_m == pytest.approx(20.0)
    assert target.down_m == pytest.approx(expected_down_m)


def test_relative_forward_move_uses_diagonal_heading():
    """대각선 기수 방향의 전진 벡터를 두 NED 축으로 나눈다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    target = calculator.calculate_relative_target(
        current_position=make_current_position(),
        heading_rad=math.pi / 4.0,
        direction="forward",
        distance_m=math.sqrt(2.0),
    )

    assert target.north_m == pytest.approx(11.0)
    assert target.east_m == pytest.approx(21.0)
    assert target.down_m == pytest.approx(-3.0)


@pytest.mark.parametrize(
    "distance_m",
    [
        0.0,
        -1.0,
    ],
)
def test_relative_move_rejects_non_positive_distance(distance_m):
    """0 이하의 상대이동 거리를 거부한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="greater than zero",
    ):
        calculator.calculate_relative_target(
            current_position=make_current_position(),
            heading_rad=0.0,
            direction="forward",
            distance_m=distance_m,
        )


@pytest.mark.parametrize(
    "direction",
    [
        "north",
        "clockwise",
        "",
        None,
    ],
)
def test_relative_move_rejects_unsupported_direction(direction):
    """Function Schema에 없는 상대이동 방향을 거부한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="direction",
    ):
        calculator.calculate_relative_target(
            current_position=make_current_position(),
            heading_rad=0.0,
            direction=direction,
            distance_m=1.0,
        )


@pytest.mark.parametrize(
    "heading_rad",
    [
        math.nan,
        math.inf,
        -math.inf,
        math.pi + 0.01,
        -math.pi - 0.01,
    ],
)
def test_relative_move_rejects_invalid_heading(heading_rad):
    """유효하지 않은 PX4 기수 방향을 거부한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )

    with pytest.raises(CoordinateCalculationError):
        calculator.calculate_relative_target(
            current_position=make_current_position(),
            heading_rad=heading_rad,
            direction="forward",
            distance_m=1.0,
        )


def test_relative_move_rejects_non_finite_current_position():
    """유효하지 않은 현재 위치로 상대 목표를 만들지 못하게 한다."""
    calculator = CoordinateCalculator(
        home_position=make_home_position()
    )
    invalid_position = NedPosition(
        north_m=math.nan,
        east_m=0.0,
        down_m=-2.0,
    )

    with pytest.raises(
        CoordinateCalculationError,
        match="current_position.north_m",
    ):
        calculator.calculate_relative_target(
            current_position=invalid_position,
            heading_rad=0.0,
            direction="forward",
            distance_m=1.0,
        )
