"""상대 회전 명령을 PX4 NED 목표 yaw로 변환한다."""

import math


class YawCalculationError(ValueError):
    """목표 yaw 계산에 사용할 수 없는 값이 입력되면 발생한다."""


def _require_finite(
    value_name: str,
    value: float,
) -> float:
    """입력값을 float로 변환하고 유한한 숫자인지 확인한다."""
    # Python에서는 bool도 숫자로 변환될 수 있으므로 명시적으로 거부한다.
    if isinstance(value, bool):
        raise YawCalculationError(
            f"{value_name} must be a finite number"
        )

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as error:
        raise YawCalculationError(
            f"{value_name} must be a finite number"
        ) from error

    # NaN과 양수·음수 무한대가 PX4로 전달되지 않게 한다.
    if not math.isfinite(numeric_value):
        raise YawCalculationError(
            f"{value_name} must be a finite number"
        )

    return numeric_value


def normalize_yaw_rad(yaw_rad: float) -> float:
    """
    yaw를 PX4에서 사용하기 쉬운 -pi 이상 pi 미만 범위로 정규화한다.

    같은 방향을 나타내는 여러 각도를 하나의 범위로 통일한다.
    예를 들어 270도는 -90도와 같은 방향이므로 -pi/2로 변환된다.
    """
    numeric_yaw_rad = _require_finite(
        "yaw_rad",
        yaw_rad,
    )

    normalized_yaw_rad = (
        (numeric_yaw_rad + math.pi)
        % (2.0 * math.pi)
        - math.pi
    )

    # 부동소수점 계산으로 -0.0이 생기지 않도록 0.0으로 통일한다.
    if math.isclose(
        normalized_yaw_rad,
        0.0,
        abs_tol=1e-12,
    ):
        return 0.0

    return normalized_yaw_rad


def calculate_relative_yaw_target(
    current_heading_rad: float,
    yaw_deg: float,
) -> float:
    """
    현재 기수 방향과 상대 회전각으로 PX4 목표 yaw를 계산한다.

    current_heading_rad는 PX4 VehicleLocalPosition.heading 값이다.
    PX4 로컬 NED 좌표계에서는 0라디안이 북쪽이고,
    양수 방향으로 증가하면 동쪽을 향해 시계 방향으로 회전한다.

    Function Schema의 yaw_deg도 오른쪽 회전이 양수이고
    왼쪽 회전이 음수이므로 두 값을 같은 부호로 더한다.
    """
    current_yaw_rad = _require_finite(
        "current_heading_rad",
        current_heading_rad,
    )
    relative_yaw_deg = _require_finite(
        "yaw_deg",
        yaw_deg,
    )

    # PX4에서 전달되는 heading 값의 정상 범위를 확인한다.
    # 이 범위를 벗어나면 degree 값을 잘못 전달했을 가능성도 차단한다.
    if not -math.pi <= current_yaw_rad <= math.pi:
        raise YawCalculationError(
            "current_heading_rad must be between -pi and pi"
        )

    relative_yaw_rad = math.radians(relative_yaw_deg)
    target_yaw_rad = current_yaw_rad + relative_yaw_rad

    return normalize_yaw_rad(target_yaw_rad)


def calculate_yaw_error_rad(
    current_yaw_rad: float,
    target_yaw_rad: float,
) -> float:
    """
    현재 yaw와 목표 yaw 사이의 가장 짧은 각도 오차를 반환한다.

    반환값은 0 이상 pi 이하의 라디안 값이다.
    예를 들어 현재 179도와 목표 -179도의 차이는
    358도가 아니라 가장 짧은 회전 거리인 2도로 계산한다.
    """
    current_yaw = _require_finite(
        "current_yaw_rad",
        current_yaw_rad,
    )
    target_yaw = _require_finite(
        "target_yaw_rad",
        target_yaw_rad,
    )

    yaw_difference_rad = normalize_yaw_rad(
        target_yaw - current_yaw
    )

    return abs(yaw_difference_rad)


def has_reached_yaw(
    current_yaw_rad: float,
    target_yaw_rad: float,
    tolerance_deg: float,
) -> bool:
    """현재 기수 방향이 목표 yaw의 허용 오차 안인지 확인한다."""
    yaw_tolerance_deg = _require_finite(
        "tolerance_deg",
        tolerance_deg,
    )

    if yaw_tolerance_deg < 0.0:
        raise YawCalculationError(
            "tolerance_deg cannot be negative"
        )

    yaw_error_rad = calculate_yaw_error_rad(
        current_yaw_rad=current_yaw_rad,
        target_yaw_rad=target_yaw_rad,
    )
    tolerance_rad = math.radians(yaw_tolerance_deg)

    # degree를 radian으로 변환할 때 발생하는 미세한 표현 오차로
    # 정확한 허용 경계값이 실패하지 않도록 절대 오차를 허용한다.
    return (
        yaw_error_rad <= tolerance_rad
        or math.isclose(
            yaw_error_rad,
            tolerance_rad,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
