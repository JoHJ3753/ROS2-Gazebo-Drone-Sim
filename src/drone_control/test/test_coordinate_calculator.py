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
