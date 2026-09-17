"""사용자 기준 좌표를 PX4 로컬 NED 목표 좌표로 변환한다."""

from dataclasses import dataclass
import math


class CoordinateCalculationError(ValueError):
    """좌표 계산에 사용할 수 없는 값이 입력되면 발생한다."""


@dataclass(frozen=True)
class NedPosition:
    """
    PX4 로컬 NED 좌표계의 위치를 표현한다.

    north_m은 북쪽, east_m은 동쪽, down_m은 아래쪽이 양수다.
    따라서 상승한 위치의 down_m 값은 홈 위치보다 작아진다.
    """

    north_m: float
    east_m: float
    down_m: float

    def as_px4_tuple(self) -> tuple[float, float, float]:
        """PX4 TrajectorySetpoint에서 사용하는 x, y, z 순서로 반환한다."""
        return (
            self.north_m,
            self.east_m,
            self.down_m,
        )


def _require_finite(
    value_name: str,
    value: float,
) -> float:
    """좌표값을 float로 변환하고 유한한 숫자인지 확인한다."""
    if isinstance(value, bool):
        raise CoordinateCalculationError(
            f"{value_name} must be a finite number"
        )

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as error:
        raise CoordinateCalculationError(
            f"{value_name} must be a finite number"
        ) from error

    if not math.isfinite(numeric_value):
        raise CoordinateCalculationError(
            f"{value_name} must be a finite number"
        )

    return numeric_value


class CoordinateCalculator:
    """
    홈 기준 명령 좌표를 PX4 로컬 NED 절대좌표로 변환한다.

    사용자가 입력하는 altitude_m은 홈 위치보다 위쪽인 높이를
    양수로 표현한다. PX4 NED에서는 아래쪽이 +Z이므로 계산할 때
    홈의 down_m 값에서 altitude_m을 뺀다.
    """

    def __init__(self, home_position: NedPosition) -> None:
        """검증된 PX4 홈 위치를 저장한다."""
        self._home_position = NedPosition(
            north_m=_require_finite(
                "home_position.north_m",
                home_position.north_m,
            ),
            east_m=_require_finite(
                "home_position.east_m",
                home_position.east_m,
            ),
            down_m=_require_finite(
                "home_position.down_m",
                home_position.down_m,
            ),
        )

    @property
    def home_position(self) -> NedPosition:
        """저장된 홈 위치를 반환한다."""
        return self._home_position

    def calculate_absolute_target(
        self,
        north_m: float,
        east_m: float,
        altitude_m: float,
    ) -> NedPosition:
        """
        홈 기준 절대 명령 좌표를 PX4 NED 목표 좌표로 변환한다.

        north_m과 east_m은 홈으로부터 각각 북쪽과 동쪽 거리다.
        altitude_m은 홈 높이를 0m로 하는 위쪽 고도다.
        """
        north_offset_m = _require_finite(
            "north_m",
            north_m,
        )
        east_offset_m = _require_finite(
            "east_m",
            east_m,
        )
        target_altitude_m = _require_finite(
            "altitude_m",
            altitude_m,
        )

        if target_altitude_m < 0.0:
            raise CoordinateCalculationError(
                "altitude_m cannot be negative"
            )

        return NedPosition(
            north_m=(
                self._home_position.north_m
                + north_offset_m
            ),
            east_m=(
                self._home_position.east_m
                + east_offset_m
            ),
            down_m=(
                self._home_position.down_m
                - target_altitude_m
            ),
        )
