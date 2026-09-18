"""PX4 상대 yaw 목표 계산 기능을 검증한다."""

import math

import pytest

from drone_control.yaw_calculator import (
    YawCalculationError,
    calculate_relative_yaw_target,
    calculate_yaw_error_rad,
    has_reached_yaw,
    normalize_yaw_rad,
)


@pytest.mark.parametrize(
    ("input_yaw_rad", "expected_yaw_rad"),
    [
        (0.0, 0.0),
        (math.pi / 2.0, math.pi / 2.0),
        (3.0 * math.pi / 2.0, -math.pi / 2.0),
        (-3.0 * math.pi / 2.0, math.pi / 2.0),
        (math.pi, -math.pi),
        (2.0 * math.pi, 0.0),
    ],
)
def test_normalize_yaw_rad_uses_px4_range(
    input_yaw_rad,
    expected_yaw_rad,
):
    """여러 yaw 표현을 -pi 이상 pi 미만 범위로 변환한다."""
    normalized_yaw_rad = normalize_yaw_rad(input_yaw_rad)

    assert normalized_yaw_rad == pytest.approx(
        expected_yaw_rad
    )


def test_right_rotation_increases_yaw():
    """북쪽에서 오른쪽 90도 회전하면 동쪽을 향한다."""
    target_yaw_rad = calculate_relative_yaw_target(
        current_heading_rad=0.0,
        yaw_deg=90.0,
    )

    assert target_yaw_rad == pytest.approx(
        math.pi / 2.0
    )


def test_left_rotation_decreases_yaw():
    """북쪽에서 왼쪽 90도 회전하면 서쪽을 향한다."""
    target_yaw_rad = calculate_relative_yaw_target(
        current_heading_rad=0.0,
        yaw_deg=-90.0,
    )

    assert target_yaw_rad == pytest.approx(
        -math.pi / 2.0
    )


def test_right_rotation_wraps_at_pi_boundary():
    """동쪽에서 오른쪽 90도 회전하면 남쪽 방향으로 정규화한다."""
    target_yaw_rad = calculate_relative_yaw_target(
        current_heading_rad=math.pi / 2.0,
        yaw_deg=90.0,
    )

    # +pi와 -pi는 모두 남쪽을 나타내며 정규화 결과는 -pi다.
    assert target_yaw_rad == pytest.approx(-math.pi)


def test_left_rotation_wraps_at_negative_pi_boundary():
    """서쪽에서 왼쪽 90도 회전하면 남쪽 방향으로 정규화한다."""
    target_yaw_rad = calculate_relative_yaw_target(
        current_heading_rad=-math.pi / 2.0,
        yaw_deg=-90.0,
    )

    assert target_yaw_rad == pytest.approx(-math.pi)


def test_rotation_larger_than_full_turn_is_normalized():
    """한 바퀴를 넘는 회전각도 최종 목표 방향으로 정규화한다."""
    target_yaw_rad = calculate_relative_yaw_target(
        current_heading_rad=0.0,
        yaw_deg=450.0,
    )

    # 오른쪽 450도는 오른쪽 90도와 같은 목표 방향이다.
    assert target_yaw_rad == pytest.approx(
        math.pi / 2.0
    )


@pytest.mark.parametrize(
    ("current_heading_rad", "yaw_deg"),
    [
        (math.nan, 90.0),
        (math.inf, 90.0),
        (-math.inf, 90.0),
        (0.0, math.nan),
        (0.0, math.inf),
        (0.0, -math.inf),
    ],
)
def test_non_finite_rotation_value_is_rejected(
    current_heading_rad,
    yaw_deg,
):
    """유한하지 않은 회전값이 목표 yaw로 전달되지 않게 한다."""
    with pytest.raises(
        YawCalculationError,
        match="must be a finite number",
    ):
        calculate_relative_yaw_target(
            current_heading_rad=current_heading_rad,
            yaw_deg=yaw_deg,
        )


@pytest.mark.parametrize(
    ("current_heading_rad", "yaw_deg"),
    [
        (True, 90.0),
        (0.0, False),
    ],
)
def test_boolean_rotation_value_is_rejected(
    current_heading_rad,
    yaw_deg,
):
    """Boolean 값이 숫자 회전각으로 처리되지 않게 한다."""
    with pytest.raises(
        YawCalculationError,
        match="must be a finite number",
    ):
        calculate_relative_yaw_target(
            current_heading_rad=current_heading_rad,
            yaw_deg=yaw_deg,
        )


@pytest.mark.parametrize(
    "invalid_heading_rad",
    [
        math.pi + 0.01,
        -math.pi - 0.01,
    ],
)
def test_heading_outside_px4_range_is_rejected(
    invalid_heading_rad,
):
    """PX4 heading 정상 범위를 벗어난 입력을 거부한다."""
    with pytest.raises(
        YawCalculationError,
        match="must be between -pi and pi",
    ):
        calculate_relative_yaw_target(
            current_heading_rad=invalid_heading_rad,
            yaw_deg=90.0,
        )


def test_yaw_error_uses_shortest_path_across_pi_boundary():
    """양수와 음수 pi 경계에서 가장 짧은 각도 차이를 계산한다."""
    current_yaw_rad = math.radians(179.0)
    target_yaw_rad = math.radians(-179.0)

    yaw_error_rad = calculate_yaw_error_rad(
        current_yaw_rad=current_yaw_rad,
        target_yaw_rad=target_yaw_rad,
    )

    assert math.degrees(yaw_error_rad) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("current_yaw_deg", "target_yaw_deg", "expected"),
    [
        (90.0, 90.0, True),
        (87.0, 90.0, True),
        (93.0, 90.0, True),
        (86.9, 90.0, False),
        (93.1, 90.0, False),
        (179.0, -179.0, True),
    ],
)
def test_has_reached_yaw_uses_angular_tolerance(
    current_yaw_deg,
    target_yaw_deg,
    expected,
):
    """목표 yaw와의 최단 각도 차이로 회전 완료 여부를 판정한다."""
    reached = has_reached_yaw(
        current_yaw_rad=math.radians(current_yaw_deg),
        target_yaw_rad=math.radians(target_yaw_deg),
        tolerance_deg=3.0,
    )

    assert reached is expected


def test_has_reached_yaw_rejects_negative_tolerance():
    """음수 yaw 허용 오차를 거부한다."""
    with pytest.raises(
        YawCalculationError,
        match="cannot be negative",
    ):
        has_reached_yaw(
            current_yaw_rad=0.0,
            target_yaw_rad=math.pi / 2.0,
            tolerance_deg=-1.0,
        )


@pytest.mark.parametrize(
    ("current_yaw_rad", "target_yaw_rad"),
    [
        (math.nan, 0.0),
        (0.0, math.nan),
        (math.inf, 0.0),
        (0.0, -math.inf),
    ],
)
def test_yaw_error_rejects_non_finite_value(
    current_yaw_rad,
    target_yaw_rad,
):
    """유한하지 않은 yaw가 회전 완료 판정에 사용되지 않게 한다."""
    with pytest.raises(
        YawCalculationError,
        match="must be a finite number",
    ):
        calculate_yaw_error_rad(
            current_yaw_rad=current_yaw_rad,
            target_yaw_rad=target_yaw_rad,
        )
