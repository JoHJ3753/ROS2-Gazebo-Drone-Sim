"""사용자 기준 좌표를 PX4 로컬 NED 목표 좌표로 변환한다."""

from dataclasses import dataclass
import math


_RELATIVE_DIRECTIONS = frozenset(
    {
        "forward",
        "backward",
        "left",
        "right",
        "up",
        "down",
    }
)


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
    사용자 명령 좌표를 PX4 로컬 NED 목표좌표로 변환한다.

    절대좌표는 저장된 홈 위치를 기준으로 계산한다.
    상대좌표는 명령 시작 시점의 현재 위치와 기수 방향을 기준으로
    계산한다.

    PX4 NED 좌표계:
        +X: 북쪽
        +Y: 동쪽
        +Z: 아래쪽

    사용자가 입력하는 altitude_m과 up 방향은 위쪽을 양수로
    표현하므로 PX4 down 좌표에서는 값을 빼야 한다.
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

    def calculate_relative_target(
        self,
        current_position: NedPosition,
        heading_rad: float,
        direction: str,
        distance_m: float,
    ) -> NedPosition:
        """
        현재 위치와 기수 방향을 기준으로 상대이동 목표를 계산한다.

        heading_rad는 PX4 VehicleLocalPosition.heading 값이다.
        0 라디안은 북쪽이며 양수 방향은 동쪽으로 회전한다.
        direction은 Function Schema의 move_drone 표준값을 사용한다.
        """
        current_north_m = _require_finite(
            "current_position.north_m",
            current_position.north_m,
        )
        current_east_m = _require_finite(
            "current_position.east_m",
            current_position.east_m,
        )
        current_down_m = _require_finite(
            "current_position.down_m",
            current_position.down_m,
        )
        current_heading_rad = _require_finite(
            "heading_rad",
            heading_rad,
        )
        travel_distance_m = _require_finite(
            "distance_m",
            distance_m,
        )

        if not isinstance(direction, str):
            raise CoordinateCalculationError(
                "direction must be a supported string"
            )

        if direction not in _RELATIVE_DIRECTIONS:
            raise CoordinateCalculationError(
                f"unsupported relative direction: {direction}"
            )

        if travel_distance_m <= 0.0:
            raise CoordinateCalculationError(
                "distance_m must be greater than zero"
            )

        # PX4 heading은 -PI부터 +PI 사이의 라디안 값이다.
        # 이 범위를 벗어나면 degree를 잘못 전달했을 가능성도 차단한다.
        if not -math.pi <= current_heading_rad <= math.pi:
            raise CoordinateCalculationError(
                "heading_rad must be between -pi and pi"
            )

        current = NedPosition(
            north_m=current_north_m,
            east_m=current_east_m,
            down_m=current_down_m,
        )

        # 수직 이동은 현재 기수 방향과 관계없이 NED Z축만 변경한다.
        if direction == "up":
            return NedPosition(
                north_m=current.north_m,
                east_m=current.east_m,
                down_m=current.down_m - travel_distance_m,
            )

        if direction == "down":
            return NedPosition(
                north_m=current.north_m,
                east_m=current.east_m,
                down_m=current.down_m + travel_distance_m,
            )

        # 기체 기준 이동량을 forward와 right 축으로 표현한다.
        forward_m = 0.0
        right_m = 0.0

        if direction == "forward":
            forward_m = travel_distance_m
        elif direction == "backward":
            forward_m = -travel_distance_m
        elif direction == "right":
            right_m = travel_distance_m
        elif direction == "left":
            right_m = -travel_distance_m

        # 기체 기준 벡터를 PX4 NED의 North와 East 벡터로 회전한다.
        north_delta_m = (
            forward_m * math.cos(current_heading_rad)
            - right_m * math.sin(current_heading_rad)
        )
        east_delta_m = (
            forward_m * math.sin(current_heading_rad)
            + right_m * math.cos(current_heading_rad)
        )

        return NedPosition(
            north_m=current.north_m + north_delta_m,
            east_m=current.east_m + east_delta_m,
            down_m=current.down_m,
        )
