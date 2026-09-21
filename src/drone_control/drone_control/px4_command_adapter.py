"""PX4 Offboard 통신을 담당하는 ROS 2 어댑터 노드."""

from enum import Enum
import math
import os
import time
import json

from px4_msgs.msg import OffboardControlMode
from px4_msgs.msg import TrajectorySetpoint
from px4_msgs.msg import VehicleCommand
from px4_msgs.msg import VehicleLocalPosition
from px4_msgs.msg import VehicleStatus
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy

from std_msgs.msg import String

from drone_control.command_executor import CommandExecutionError
from drone_control.command_executor import CommandExecutor

from drone_control.coordinate_calculator import CoordinateCalculationError
from drone_control.coordinate_calculator import CoordinateCalculator
from drone_control.coordinate_calculator import NedPosition
from drone_control.yaw_calculator import (
    YawCalculationError,
    calculate_relative_yaw_target,
    calculate_yaw_error_rad,
    has_reached_yaw,
)


# 이 파일의 첫 번째 버전은 Gazebo 시뮬레이션 검증용이다.
# 실제 기체에 적용하기 전에는 별도의 안전 검증이 필요하다.
NODE_NAME = "px4_command_adapter"

VALIDATED_COMMAND_TOPIC = "/drone/validated_command"
FLIGHT_STATUS_TOPIC = "/drone/flight_status"

CONTROL_PERIOD_SECONDS = 0.1
SETPOINT_STREAM_COUNT = 20
COMMAND_RETRY_INTERVAL_TICKS = 10

REQUIRED_ROS_DOMAIN_ID = 42
MESSAGE_FRESHNESS_TIMEOUT_SECONDS = 1.0
START_STABILITY_REQUIRED_TICKS = 20

MAX_START_HORIZONTAL_SPEED_MPS = 0.15
MAX_START_VERTICAL_SPEED_MPS = 0.10
MAX_START_HEADING_DRIFT_DEG = 3.0

EXPECTED_COMMAND_PUBLISHER_COUNT = 1
PX4_COMMAND_TOPICS = (
    "/fmu/in/offboard_control_mode",
    "/fmu/in/trajectory_setpoint",
    "/fmu/in/vehicle_command",
)

DEFAULT_TAKEOFF_HEIGHT_M = 2.0
DEFAULT_TARGET_NORTH_M = 1.0
DEFAULT_TARGET_EAST_M = 0.0
DEFAULT_TARGET_ALTITUDE_M = 2.0

# 목표좌표 계산 방식을 구분한다.
#
# absolute:
#   이륙 시작 위치를 원점으로 사용하는 절대좌표 방식
#
# relative:
#   명령 실행 시점의 기체 위치와 기수 방향을 기준으로
#   앞·뒤·왼쪽·오른쪽 등의 상대좌표를 계산하는 방식
TARGET_MODE_TAKEOFF = "takeoff"
TARGET_MODE_ABSOLUTE = "absolute"
TARGET_MODE_RELATIVE = "relative"
TARGET_MODE_ROTATION = "rotation"

SUPPORTED_TARGET_MODES = frozenset(
    {
        TARGET_MODE_TAKEOFF,
        TARGET_MODE_ABSOLUTE,
        TARGET_MODE_RELATIVE,
        TARGET_MODE_ROTATION,
    }
)


DEFAULT_TARGET_MODE = TARGET_MODE_ABSOLUTE
DEFAULT_RELATIVE_DIRECTION = "forward"
DEFAULT_RELATIVE_DISTANCE_M = 1.0
DEFAULT_RELATIVE_YAW_DEG = 90.0

TAKEOFF_ALTITUDE_TOLERANCE_M = 0.15
TARGET_POSITION_TOLERANCE_M = 0.2
TARGET_YAW_TOLERANCE_DEG = 3.0
FLOAT_COMPARISON_ABS_TOLERANCE = 1e-6


PX4_TARGET_SYSTEM_ID = 1
PX4_TARGET_COMPONENT_ID = 1
PX4_SOURCE_SYSTEM_ID = 1
PX4_SOURCE_COMPONENT_ID = 1

PX4_CUSTOM_MAIN_MODE = 1.0
PX4_OFFBOARD_SUB_MODE = 6.0


def calculate_takeoff_target(
    current_x_m: float,
    current_y_m: float,
    current_z_m: float,
    height_m: float,
) -> tuple[float, float, float]:
    """
    현재 NED 위치를 기준으로 수직 이륙 목표를 계산한다.

    PX4 NED 좌표계에서는 아래 방향이 +Z이므로 상승하려면
    현재 z 값에서 이륙 높이를 빼야 한다.
    """
    if height_m <= 0.0:
        raise ValueError("Takeoff height must be greater than zero")

    return (
        float(current_x_m),
        float(current_y_m),
        float(current_z_m - height_m),
    )


def is_vehicle_ready(
    position: VehicleLocalPosition | None,
    status: VehicleStatus | None,
) -> bool:
    """
    기체가 안전하게 자동 제어를 시작할 수 있는지 확인한다.

    VehicleLandDetected가 현재 PX4 DDS 출력에 포함되지 않으므로
    무장 상태, 비행 시간, 위치 유효성, 속도 안정성을 조합해
    지상 대기 상태를 보수적으로 판정한다.
    """
    if position is None or status is None:
        return False

    if status.arming_state != VehicleStatus.ARMING_STATE_DISARMED:
        return False

    if status.failsafe or not status.pre_flight_checks_pass:
        return False

    if status.armed_time != 0 or status.takeoff_time != 0:
        return False

    if not position.xy_valid or not position.z_valid:
        return False

    if not position.v_xy_valid or not position.v_z_valid:
        return False

    values = (
        position.x,
        position.y,
        position.z,
        position.vx,
        position.vy,
        position.vz,
        position.heading,
    )

    if not all(math.isfinite(float(value)) for value in values):
        return False

    horizontal_speed_mps = math.hypot(
        float(position.vx),
        float(position.vy),
    )

    if horizontal_speed_mps > MAX_START_HORIZONTAL_SPEED_MPS:
        return False

    return abs(float(position.vz)) <= MAX_START_VERTICAL_SPEED_MPS


def has_reached_altitude(
    current_z_m: float,
    target_z_m: float,
    tolerance_m: float,
) -> bool:
    """
    현재 고도가 목표 고도의 허용 오차 안인지 확인한다.

    부동소수점 계산에서는 0.15가 0.15000000000000036처럼
    표현될 수 있으므로 경계값에 작은 절대 오차를 허용한다.
    """
    if tolerance_m < 0.0:
        raise ValueError("Altitude tolerance cannot be negative")

    altitude_error_m = abs(current_z_m - target_z_m)

    return (
        altitude_error_m <= tolerance_m
        or math.isclose(
            altitude_error_m,
            tolerance_m,
            rel_tol=0.0,
            abs_tol=FLOAT_COMPARISON_ABS_TOLERANCE,
        )
    )


def has_reached_position(
    current_position: tuple[float, float, float],
    target_position: tuple[float, float, float],
    tolerance_m: float,
) -> bool:
    """
    현재 위치가 목표 위치의 허용 거리 안인지 확인한다.

    current_position과 target_position은 PX4 로컬 NED 좌표계의
    x, y, z 순서다. 세 축의 직선거리를 계산해 도달 여부를 판단한다.
    """
    if tolerance_m < 0.0:
        raise ValueError("Position tolerance cannot be negative")

    # 세 축의 차이를 함께 계산해야 대각선 방향의 오차도
    # 실제 공간상의 거리로 올바르게 판정할 수 있다.
    position_error_m = math.dist(
        current_position,
        target_position,
    )

    # 부동소수점 표현 오차 때문에 정확한 경계값이 실패하지 않도록
    # 기존 고도 판정 함수와 동일한 작은 절대 오차를 허용한다.
    return (
        position_error_m <= tolerance_m
        or math.isclose(
            position_error_m,
            tolerance_m,
            rel_tol=0.0,
            abs_tol=FLOAT_COMPARISON_ABS_TOLERANCE,
        )
    )


def validate_target_mode(target_mode: str) -> str:
    """목표좌표 계산 모드가 지원되는 값인지 검증한다."""
    if not isinstance(target_mode, str):
        raise ValueError("target_mode must be a string")

    if target_mode not in SUPPORTED_TARGET_MODES:
        raise ValueError(
            "target_mode must be 'takeoff', 'absolute', "
            "'relative', or 'rotation'"
        )

    return target_mode


def is_offboard_and_armed(
    status: VehicleStatus | None,
) -> bool:
    """PX4 상태가 Offboard 모드이면서 시동 상태인지 확인한다."""
    if status is None:
        return False

    is_offboard = (
        status.nav_state
        == VehicleStatus.NAVIGATION_STATE_OFFBOARD
    )
    is_armed = (
        status.arming_state
        == VehicleStatus.ARMING_STATE_ARMED
    )
    return is_offboard and is_armed


def is_vehicle_disarmed(
    status: VehicleStatus | None,
) -> bool:
    """PX4 상태가 정상적인 시동 해제 상태인지 확인한다."""
    if status is None:
        return False

    return (
        status.arming_state
        == VehicleStatus.ARMING_STATE_DISARMED
    )


class AdapterState(Enum):
    """PX4 어댑터의 비행 제어 상태를 정의한다."""

    WAITING_FOR_READY = "waiting_for_ready"
    IDLE = "idle"
    STREAMING_SETPOINTS = "streaming_setpoints"
    REQUESTING_OFFBOARD = "requesting_offboard"
    TAKING_OFF = "taking_off"
    MOVING_TO_TARGET = "moving_to_target"
    ROTATING = "rotating"
    HOLDING = "holding"
    HOVERING = "hovering"
    LANDING = "landing"
    LANDED = "landed"
    ERROR = "error"


class Px4CommandAdapter(Node):
    """
    ROS 2 명령을 PX4 Offboard 메시지로 변환한다.

    현재 버전은 현재 수평 위치를 유지하면서 수직으로 이륙한 뒤,
    홈 기준 절대좌표 목표로 이동하고 목표 위치를 유지한다.

    PX4 NED 좌표계:
        +X: 북쪽
        +Y: 동쪽
        +Z: 아래쪽

    따라서 위로 2m 상승하려면 홈의 z 값에서 2.0을 빼야 한다.
    """

    def __init__(self) -> None:
        """PX4 발행자, 구독자와 제어 타이머를 생성한다."""
        super().__init__(NODE_NAME)

        actual_domain_id = os.environ.get("ROS_DOMAIN_ID", "0")

        if actual_domain_id != str(REQUIRED_ROS_DOMAIN_ID):
            raise RuntimeError(
                "ROS_DOMAIN_ID must be "
                f"{REQUIRED_ROS_DOMAIN_ID}, "
                f"but received {actual_domain_id}"
            )

        # 현재는 시뮬레이션 검증을 위해 ROS 2 파라미터로 목표를 받는다.
        # 이후 검증된 LLM 명령 실행기가 이 값들을 전달하도록 연결할 수 있다.
        self._target_north_m = float(
            self.declare_parameter(
                "target_north_m",
                DEFAULT_TARGET_NORTH_M,
            ).value
        )
        self._target_east_m = float(
            self.declare_parameter(
                "target_east_m",
                DEFAULT_TARGET_EAST_M,
            ).value
        )
        self._target_altitude_m = float(
            self.declare_parameter(
                "target_altitude_m",
                DEFAULT_TARGET_ALTITUDE_M,
            ).value
        )
        # 이동 방식과 상대이동 명령을 ROS 2 파라미터로 받는다.
        # 이후에는 검증된 LLM 명령 실행기가 이 값을 전달하게 된다.
        self._target_mode = str(
            self.declare_parameter(
                "target_mode",
                DEFAULT_TARGET_MODE,
            ).value
        )
        self._relative_direction = str(
            self.declare_parameter(
                "relative_direction",
                DEFAULT_RELATIVE_DIRECTION,
            ).value
        )
        self._relative_distance_m = float(
            self.declare_parameter(
                "relative_distance_m",
                DEFAULT_RELATIVE_DISTANCE_M,
            ).value
        )
        self._relative_yaw_deg = float(
            self.declare_parameter(
                "relative_yaw_deg",
                DEFAULT_RELATIVE_YAW_DEG,
            ).value
        )

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self._offboard_control_mode_publisher = self.create_publisher(
            OffboardControlMode,
            "/fmu/in/offboard_control_mode",
            qos_profile,
        )
        self._trajectory_setpoint_publisher = self.create_publisher(
            TrajectorySetpoint,
            "/fmu/in/trajectory_setpoint",
            qos_profile,
        )
        self._vehicle_command_publisher = self.create_publisher(
            VehicleCommand,
            "/fmu/in/vehicle_command",
            qos_profile,
        )

        self._vehicle_local_position_subscription = (
            self.create_subscription(
                VehicleLocalPosition,
                "/fmu/out/vehicle_local_position",
                self._vehicle_local_position_callback,
                qos_profile,
            )
        )
        self._vehicle_status_subscription = self.create_subscription(
            VehicleStatus,
            "/fmu/out/vehicle_status",
            self._vehicle_status_callback,
            qos_profile,
        )

        # 검증된 단일 명령만 실행기에 전달한다.
        self._command_executor = CommandExecutor(self)

        # LLM 출력 파서와 검증 경계를 통과한 명령을 받는다.
        self._validated_command_subscription = self.create_subscription(
            String,
            VALIDATED_COMMAND_TOPIC,
            self._validated_command_callback,
            10,
        )
        self._flight_status_publisher = self.create_publisher(
            String,
            FLIGHT_STATUS_TOPIC,
            10,
        )

        self._state = AdapterState.WAITING_FOR_READY
        self._vehicle_local_position: VehicleLocalPosition | None = None
        self._vehicle_status: VehicleStatus | None = None
        self._last_position_received_at: float | None = None
        self._last_status_received_at: float | None = None
        self._start_stability_counter = 0
        self._start_reset_signature: tuple[int, int, int] | None = None
        self._start_heading_rad: float | None = None

        # _target_position은 현재 PX4에 전송하는 목표다.
        # 이륙 중에는 수직 이륙 목표이고, 이륙 완료 후에는
        # 최종 절대좌표 목표로 교체된다.
        self._target_position: tuple[float, float, float] | None = None

        # 최종 절대좌표 목표는 이륙 목표와 구분해 보관한다.
        self._mission_target_position: (
            tuple[float, float, float] | None
        ) = None

        # 홈 위치로 생성한 좌표 계산기를 보관한다.
        # 상대이동에서는 이륙 완료 시점의 현재 좌표를 전달해 사용한다.
        self._coordinate_calculator: CoordinateCalculator | None = None

        self._target_yaw_rad = 0.0

        self._hover_deadline_monotonic: float | None = None

        self._setpoint_stream_counter = 0
        self._command_retry_counter = 0

        self._timer = self.create_timer(
            CONTROL_PERIOD_SECONDS,
            self._timer_callback,
        )

        self.get_logger().info(
            "PX4 adapter started. Waiting for valid vehicle data."
        )

    def _vehicle_local_position_callback(
        self,
        message: VehicleLocalPosition,
    ) -> None:
        """PX4의 최신 로컬 위치를 저장한다."""
        self._vehicle_local_position = message
        self._last_position_received_at = time.monotonic()

    def _vehicle_status_callback(
        self,
        message: VehicleStatus,
    ) -> None:
        """PX4의 최신 시동 상태와 비행 모드를 저장한다."""
        self._vehicle_status = message
        self._last_status_received_at = time.monotonic()

    def _validated_command_callback(self, message: String) -> None:
        """검증된 JSON 명령 하나를 수신해 실행기에 전달한다."""
        self.get_logger().info(
            "Validated command received: "
            f"topic={VALIDATED_COMMAND_TOPIC}, "
            f"payload={message.data}"
        )

        try:
            command = json.loads(message.data)
            self._command_executor.execute(command)
        except json.JSONDecodeError as error:
            self.get_logger().error(
                f"Command JSON decoding failed: {error}"
            )
            self._publish_flight_status(f"명령 거부: JSON 오류: {error}")
        except (CommandExecutionError, RuntimeError) as error:
            self.get_logger().error(
                f"Command execution rejected: {error}"
            )
            self._publish_flight_status(f"명령 거부: {error}")

    def _publish_flight_status(self, status: str) -> None:
        """실제 PX4 제어 상태를 CLI에 알린다."""
        message = String()
        message.data = status
        self._flight_status_publisher.publish(message)

    def takeoff(self, altitude_m: float) -> None:
        """명령 대기 상태에서 지정한 높이로 수직 이륙을 시작한다."""
        if self._state is not AdapterState.IDLE:
            raise RuntimeError(
                "Takeoff command requires the adapter to be idle"
            )

        if not self._messages_are_fresh():
            raise RuntimeError(
                "PX4 position or status message is stale"
            )

        if not self._is_vehicle_ready():
            raise RuntimeError(
                "Vehicle is not ready for takeoff"
            )

        self._target_mode = TARGET_MODE_TAKEOFF
        self._mission_target_position = None
        self._coordinate_calculator = None

        self._prepare_takeoff_target(altitude_m)

        self._setpoint_stream_counter = 0
        self._command_retry_counter = 0
        self._state = AdapterState.STREAMING_SETPOINTS

        self.get_logger().info(
            "Takeoff command accepted: "
            f"altitude_m={altitude_m:.2f}"
        )
        self._publish_flight_status(
            f"이륙 준비 중: 목표 고도 {altitude_m:.2f}m"
        )

    def arm(self) -> None:
        """독립 시동 명령은 아직 지원하지 않는다."""
        raise RuntimeError(
            "Standalone arm command is not implemented"
        )

    def disarm(self) -> None:
        """독립 시동 해제 명령은 아직 지원하지 않는다."""
        raise RuntimeError(
            "Standalone disarm command is not implemented"
        )

    def land(self) -> None:
        """호버링 상태에서 PX4 자동 착륙을 요청한다."""
        if self._state is not AdapterState.HOLDING:
            raise RuntimeError(
                "Land command requires the adapter to be holding"
            )

        if not self._messages_are_fresh():
            raise RuntimeError(
                "PX4 position or status message is stale"
            )

        if not self._is_offboard_and_armed():
            raise RuntimeError(
                "Land command requires an armed Offboard vehicle"
            )

        # 첫 번째 착륙 명령은 수신 즉시 발행한다.
        self._request_land()
        self._command_retry_counter = 0
        self._state = AdapterState.LANDING

        self.get_logger().info(
            "Land command accepted. "
            "Waiting for PX4 landing and disarm."
        )
        self._publish_flight_status("착륙 중: PX4 자동 착륙 요청")

    def move_drone(
        self,
        direction: str,
        distance_m: float,
        speed_mps: float | None,
    ) -> None:
        """호버링 위치에서 기수 기준 상대이동을 시작한다."""
        if self._state is not AdapterState.HOLDING:
            raise RuntimeError(
                "Move command requires the adapter to be holding"
            )

        if not self._messages_are_fresh():
            raise RuntimeError(
                "PX4 position or status message is stale"
            )

        if not self._is_offboard_and_armed():
            raise RuntimeError(
                "Move command requires an armed Offboard vehicle"
            )

        if speed_mps is not None:
            raise RuntimeError(
                "Runtime move speed control is not implemented"
            )

        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required to prepare movement"
            )

        if not position.xy_valid or not position.z_valid:
            raise RuntimeError(
                "Vehicle position is not valid for movement"
            )

        held_target = self._target_position

        if held_target is None:
            raise RuntimeError(
                "Holding target is required to prepare movement"
            )

        coordinate_calculator = CoordinateCalculator(
            NedPosition(
                north_m=float(position.x),
                east_m=float(position.y),
                down_m=float(position.z),
            )
        )

        try:
            target = coordinate_calculator.calculate_relative_target(
                current_position=NedPosition(
                    north_m=float(position.x),
                    east_m=float(position.y),
                    down_m=float(position.z),
                ),
                heading_rad=float(position.heading),
                direction=direction,
                distance_m=distance_m,
            )
        except CoordinateCalculationError as error:
            raise RuntimeError(
                f"Failed to calculate runtime move target: {error}"
            ) from error

        # 이동하지 않는 축은 현재 측정값이 아니라 기존 호버링
        # 목표값을 유지해 반복 명령에 의한 위치 드리프트를 막는다.
        if direction in {
            "forward",
            "backward",
            "left",
            "right",
        }:
            target = NedPosition(
                north_m=target.north_m,
                east_m=target.east_m,
                down_m=held_target[2],
            )
        else:
            target = NedPosition(
                north_m=held_target[0],
                east_m=held_target[1],
                down_m=target.down_m,
            )

        self.get_logger().info(
            "Runtime move coordinate source: "
            "topic=/fmu/out/vehicle_local_position, "
            "frame=PX4 local NED, "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={position.z:.2f}, "
            f"heading_rad={position.heading:.3f}"
        )

        self.get_logger().info(
            "Runtime move target prepared: "
            "mode=relative, "
            "frame=PX4 local NED, "
            f"direction={direction}, "
            f"distance_m={distance_m:.2f}, "
            f"x={target.north_m:.2f}, "
            f"y={target.east_m:.2f}, "
            f"z={target.down_m:.2f}"
        )

        self._target_mode = TARGET_MODE_RELATIVE
        self._relative_direction = direction
        self._relative_distance_m = distance_m
        self._target_position = target.as_px4_tuple()
        self._state = AdapterState.MOVING_TO_TARGET

        self.get_logger().info(
            "Move command accepted. Moving to relative target."
        )
        self._publish_flight_status("이동 중: 목표 위치로 비행")

    def rotate_relative(
        self,
        yaw_deg: float,
        yaw_speed_dps: float | None,
    ) -> None:
        """호버링 위치에서 현재 기수를 기준으로 상대회전을 시작한다."""
        if self._state is not AdapterState.HOLDING:
            raise RuntimeError(
                "Rotation command requires the adapter to be holding"
            )

        if not self._messages_are_fresh():
            raise RuntimeError(
                "PX4 position or status message is stale"
            )

        if not self._is_offboard_and_armed():
            raise RuntimeError(
                "Rotation command requires an armed Offboard vehicle"
            )

        if yaw_speed_dps is not None:
            raise RuntimeError(
                "Runtime rotation speed control is not implemented"
            )

        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required to prepare rotation"
            )

        if not position.xy_valid or not position.z_valid:
            raise RuntimeError(
                "Vehicle position is not valid for rotation"
            )

        if self._target_position is None:
            raise RuntimeError(
                "Holding target is required to prepare rotation"
            )

        try:
            target_yaw_rad = calculate_relative_yaw_target(
                current_heading_rad=float(position.heading),
                yaw_deg=yaw_deg,
            )
        except YawCalculationError as error:
            raise RuntimeError(
                f"Failed to calculate runtime yaw target: {error}"
            ) from error

        self.get_logger().info(
            "Runtime rotation source: "
            "topic=/fmu/out/vehicle_local_position, "
            "frame=PX4 local NED, "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={position.z:.2f}, "
            f"heading_rad={position.heading:.3f}"
        )

        self.get_logger().info(
            "Runtime rotation target prepared: "
            "mode=rotation, "
            "frame=PX4 local NED, "
            f"relative_yaw_deg={yaw_deg:.2f}, "
            f"target_yaw_rad={target_yaw_rad:.3f}"
        )

        self._target_mode = TARGET_MODE_ROTATION
        self._relative_yaw_deg = yaw_deg
        self._target_yaw_rad = target_yaw_rad
        self._state = AdapterState.ROTATING

        self.get_logger().info(
            "Rotation command accepted. Rotating to yaw target."
        )
        self._publish_flight_status("회전 중: 목표 방향으로 기수 변경")

    def hover(self, duration_s: float | None) -> None:
        """현재 위치와 기수를 지정 시간 동안 유지한다."""
        if self._state is not AdapterState.HOLDING:
            raise RuntimeError(
                "Hover command requires the adapter to be holding"
            )

        if not self._messages_are_fresh():
            raise RuntimeError(
                "PX4 position or status message is stale"
            )

        if not self._is_offboard_and_armed():
            raise RuntimeError(
                "Hover command requires an armed Offboard vehicle"
            )

        if self._target_position is None:
            raise RuntimeError(
                "Holding target is required to hover"
            )

        if duration_s is None:
            self._hover_deadline_monotonic = None

            self.get_logger().info(
                "Hover command accepted. "
                "Holding until the next command."
            )
            self._publish_flight_status(
                "호버링 유지 중: 다음 명령 대기"
            )
            return

        self._hover_deadline_monotonic = (
            time.monotonic() + duration_s
        )
        self._state = AdapterState.HOVERING

        self.get_logger().info(
            "Timed hover command accepted: "
            f"duration_s={duration_s:.2f}"
        )
        self._publish_flight_status(
            f"호버링 중: {duration_s:.2f}초"
        )

    def _timer_callback(self) -> None:
        """안전 조건을 확인한 뒤 현재 비행 단계를 진행한다."""
        if self._state is AdapterState.ERROR:
            return

        competing_topics = self._find_competing_command_publishers()

        if competing_topics:
            self._enter_error(
                "Competing PX4 command publishers detected: "
                + ", ".join(competing_topics)
            )
            return

        if self._state is AdapterState.WAITING_FOR_READY:
            if (
                not self._messages_are_fresh()
                or not self._is_vehicle_ready()
            ):
                self._reset_start_safety_window()
                return

            if not self._update_start_safety_window():
                return

            # PX4 데이터가 안정화되어도 자동으로 이륙하지 않는다.
            # 이후 /drone/validated_command 토픽으로 takeoff 명령을
            # 받을 때까지 IDLE 상태에서 대기한다.
            self._state = AdapterState.IDLE

            self.get_logger().info(
                "Vehicle data is stable. "
                "Waiting for a validated command."
            )
            self._publish_flight_status("명령 대기 중: 기체 상태 정상")
            return

        if self._state in {
            AdapterState.IDLE,
            AdapterState.LANDED,
        }:
            return

        if not self._messages_are_fresh():
            self._enter_error(
                "PX4 position or status message became stale."
            )
            return

        # 착륙 중에는 Offboard와 Armed 상태가 해제되는 것이
        # 정상적인 상태 전환이므로 일반 비행 오류 검사보다 먼저 처리한다.
        if self._state is AdapterState.LANDING:
            self._handle_landing()
            return

        if self._vehicle_status is not None:
            if self._vehicle_status.failsafe:
                self._enter_error(
                    "PX4 entered failsafe. Stopping setpoint output."
                )
                return

        controlled_states = {
            AdapterState.TAKING_OFF,
            AdapterState.MOVING_TO_TARGET,
            AdapterState.ROTATING,
            AdapterState.HOLDING,
            AdapterState.HOVERING,
        }

        if (
            self._state in controlled_states
            and not self._is_offboard_and_armed()
        ):
            self._enter_error(
                "Offboard mode or armed state was lost. "
                "Stopping setpoint output."
            )
            return

        # PX4는 Offboard 모드로 전환하기 전에 일정 시간 이상
        # 제어 모드와 목표 위치 메시지를 받아야 한다.
        self._publish_offboard_control_mode()
        self._publish_target_position()

        if self._state is AdapterState.STREAMING_SETPOINTS:
            self._handle_setpoint_streaming()
            return

        if self._state is AdapterState.REQUESTING_OFFBOARD:
            self._handle_offboard_request()
            return

        if self._state is AdapterState.TAKING_OFF:
            self._handle_takeoff()
            return

        if self._state is AdapterState.MOVING_TO_TARGET:
            self._handle_move_to_target()
            return

        if self._state is AdapterState.ROTATING:
            self._handle_rotation()
            return

        if self._state is AdapterState.HOVERING:
            self._handle_hovering()
            return

        if self._state is AdapterState.HOLDING:
            self._monitor_holding_state()

    def _messages_are_fresh(self) -> bool:
        """PX4 위치와 상태 메시지가 최근에 수신됐는지 확인한다."""
        received_times = (
            self._last_position_received_at,
            self._last_status_received_at,
        )

        if any(value is None for value in received_times):
            return False

        now = time.monotonic()
        return all(
            now - float(received_at)
            <= MESSAGE_FRESHNESS_TIMEOUT_SECONDS
            for received_at in received_times
        )

    def _current_reset_signature(self) -> tuple[int, int, int] | None:
        """추정기 위치와 방향 재설정 카운터를 반환한다."""
        position = self._vehicle_local_position

        if position is None:
            return None

        return (
            int(position.xy_reset_counter),
            int(position.z_reset_counter),
            int(position.heading_reset_counter),
        )

    def _reset_start_safety_window(self) -> None:
        """연속 안정성 검사를 처음부터 다시 시작한다."""
        self._start_stability_counter = 0
        self._start_reset_signature = None
        self._start_heading_rad = None

    def _update_start_safety_window(self) -> bool:
        """안전 상태가 2초 동안 연속 유지됐는지 확인한다."""
        reset_signature = self._current_reset_signature()

        if reset_signature is None:
            self._reset_start_safety_window()
            return False

        if reset_signature != self._start_reset_signature:
            self._start_reset_signature = reset_signature
            self._start_heading_rad = float(
                self._vehicle_local_position.heading
            )
            self._start_stability_counter = 1
            return False

        current_heading_rad = float(
            self._vehicle_local_position.heading
        )

        if self._start_heading_rad is None:
            self._start_heading_rad = current_heading_rad
            self._start_stability_counter = 1
            return False

        heading_drift_rad = calculate_yaw_error_rad(
            current_yaw_rad=current_heading_rad,
            target_yaw_rad=self._start_heading_rad,
        )

        if (
            math.degrees(heading_drift_rad)
            > MAX_START_HEADING_DRIFT_DEG
        ):
            self._start_heading_rad = current_heading_rad
            self._start_stability_counter = 1
            return False

        self._start_stability_counter += 1
        return (
            self._start_stability_counter
            >= START_STABILITY_REQUIRED_TICKS
        )

    def _find_competing_command_publishers(self) -> list[str]:
        """자신 외에 PX4 제어 토픽 발행자가 있는지 확인한다."""
        return [
            topic_name
            for topic_name in PX4_COMMAND_TOPICS
            if self.count_publishers(topic_name)
            > EXPECTED_COMMAND_PUBLISHER_COUNT
        ]

    def _enter_error(self, message: str) -> None:
        """오류 상태로 전환해 이후 제어 메시지 발행을 막는다."""
        self._state = AdapterState.ERROR
        self.get_logger().error(message)
        self._publish_flight_status(f"비행 오류: {message}")

    def _is_vehicle_ready(self) -> bool:
        """이륙 목표를 생성할 수 있는 상태인지 확인한다."""
        return is_vehicle_ready(
            self._vehicle_local_position,
            self._vehicle_status,
        )

    def _prepare_takeoff_target(self, height_m: float) -> None:
        """현재 위치를 기준으로 수직 이륙 목표를 계산한다."""
        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required to prepare takeoff"
            )

        self._target_position = calculate_takeoff_target(
            current_x_m=position.x,
            current_y_m=position.y,
            current_z_m=position.z,
            height_m=height_m,
        )

        # 수직 이륙 중 기체가 갑자기 회전하지 않도록
        # 현재 기수 방향을 목표 yaw로 사용한다.
        if math.isfinite(position.heading):
            self._target_yaw_rad = float(position.heading)

        target_z = self._target_position[2]
        self.get_logger().info(
            "Takeoff target prepared: "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={target_z:.2f}"
        )

    def _prepare_mission_targets(self, takeoff_height_m: float) -> None:
        """
        이동 모드를 검증하고 수직 이륙과 임무 목표를 준비한다.

        잘못된 모드나 좌표가 입력되면 PX4의 Offboard 전환과
        시동이 시작되기 전에 실행을 중단한다.
        """
        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required to prepare mission"
            )

        # 문자열 오타나 지원하지 않는 이동 모드를 이륙 전에 차단한다.
        self._target_mode = validate_target_mode(self._target_mode)

        # 좌표를 어느 토픽과 좌표계에서 읽었는지 기록한다.
        self.get_logger().info(
            "Coordinate source: "
            "topic=/fmu/out/vehicle_local_position, "
            "frame=PX4 local NED, "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={position.z:.2f}, "
            f"heading_rad={position.heading:.3f}"
        )

        self._coordinate_calculator = CoordinateCalculator(
            NedPosition(
                north_m=position.x,
                east_m=position.y,
                down_m=position.z,
            )
        )

        if self._target_mode == TARGET_MODE_ABSOLUTE:
            self.get_logger().info(
                "Coordinate command input: "
                "source=ROS 2 parameters, "
                "mode=absolute, "
                "frame=home-relative, "
                f"north_m={self._target_north_m:.2f}, "
                f"east_m={self._target_east_m:.2f}, "
                f"altitude_m={self._target_altitude_m:.2f}"
            )

            mission_target = (
                self._coordinate_calculator.calculate_absolute_target(
                    north_m=self._target_north_m,
                    east_m=self._target_east_m,
                    altitude_m=self._target_altitude_m,
                )
            )
            self._mission_target_position = (
                mission_target.as_px4_tuple()
            )

            self.get_logger().info(
                "Coordinate conversion result: "
                "mode=absolute, "
                "frame=PX4 local NED, "
                f"x={mission_target.north_m:.2f}, "
                f"y={mission_target.east_m:.2f}, "
                f"z={mission_target.down_m:.2f}"
            )
        elif self._target_mode == TARGET_MODE_RELATIVE:
            self.get_logger().info(
                "Coordinate command input: "
                "source=ROS 2 parameters, "
                "mode=relative, "
                "frame=body-relative, "
                f"direction={self._relative_direction}, "
                f"distance_m={self._relative_distance_m:.2f}"
            )

            # 상대이동 목표는 이륙 후 현재 위치를 기준으로 다시 계산한다.
            # 여기서는 방향, 거리, heading 값이 유효한지만 검사한다.
            self._coordinate_calculator.calculate_relative_target(
                current_position=NedPosition(
                    north_m=position.x,
                    east_m=position.y,
                    down_m=position.z,
                ),
                heading_rad=position.heading,
                direction=self._relative_direction,
                distance_m=self._relative_distance_m,
            )
            self._mission_target_position = None

            self.get_logger().info(
                "Relative command validation completed before takeoff."
            )
        else:
            self.get_logger().info(
                "Yaw command input: "
                "source=ROS 2 parameters, "
                "mode=rotation, "
                "frame=body-relative, "
                f"yaw_deg={self._relative_yaw_deg:.2f}"
            )

            # 실제 목표 yaw는 이륙 완료 시점의 기수 방향을 기준으로
            # 다시 계산한다. 여기서는 입력값의 유효성만 검사한다.
            calculate_relative_yaw_target(
                current_heading_rad=position.heading,
                yaw_deg=self._relative_yaw_deg,
            )
            self._mission_target_position = None

            self.get_logger().info(
                "Rotation command validation completed before takeoff."
            )

        # 모든 목표 모드는 먼저 현재 x와 y를 유지하며 수직 이륙한다.
        self._prepare_takeoff_target(takeoff_height_m)

    def _prepare_post_takeoff_target(
        self,
    ) -> tuple[float, float, float]:
        """이륙 완료 시점의 목표 위치와 목표 yaw를 준비한다."""
        if self._target_mode == TARGET_MODE_ABSOLUTE:
            if self._mission_target_position is None:
                raise RuntimeError(
                    "Absolute mission target is not available"
                )

            return self._mission_target_position

        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required after takeoff"
            )

        if self._target_mode == TARGET_MODE_ROTATION:
            # 회전하는 동안 현재 위치를 그대로 유지한다.
            self._target_yaw_rad = calculate_relative_yaw_target(
                current_heading_rad=position.heading,
                yaw_deg=self._relative_yaw_deg,
            )

            self.get_logger().info(
                "Yaw conversion result: "
                "mode=rotation, "
                "frame=PX4 local NED, "
                f"current_heading_rad={position.heading:.3f}, "
                f"relative_yaw_deg={self._relative_yaw_deg:.2f}, "
                f"target_yaw_rad={self._target_yaw_rad:.3f}"
            )

            return (
                float(position.x),
                float(position.y),
                float(position.z),
            )

        coordinate_calculator = self._coordinate_calculator

        if coordinate_calculator is None:
            raise RuntimeError(
                "Coordinate calculator is not available"
            )

        # 상대이동은 지상 출발점이 아니라 수직 이륙이 끝난 순간의
        # 위치와 기수 방향을 기준으로 계산한다.
        self.get_logger().info(
            "Relative coordinate source: "
            "topic=/fmu/out/vehicle_local_position, "
            "frame=PX4 local NED, "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={position.z:.2f}, "
            f"heading_rad={position.heading:.3f}"
        )

        mission_target = (
            coordinate_calculator.calculate_relative_target(
                current_position=NedPosition(
                    north_m=position.x,
                    east_m=position.y,
                    down_m=position.z,
                ),
                heading_rad=position.heading,
                direction=self._relative_direction,
                distance_m=self._relative_distance_m,
            )
        )

        self.get_logger().info(
            "Coordinate conversion result: "
            "mode=relative, "
            "frame=PX4 local NED, "
            f"direction={self._relative_direction}, "
            f"distance_m={self._relative_distance_m:.2f}, "
            f"x={mission_target.north_m:.2f}, "
            f"y={mission_target.east_m:.2f}, "
            f"z={mission_target.down_m:.2f}"
        )

        return mission_target.as_px4_tuple()

    def _handle_setpoint_streaming(self) -> None:
        """Offboard 전환 전에 필요한 목표 메시지를 먼저 전송한다."""
        self._setpoint_stream_counter += 1

        if self._setpoint_stream_counter < SETPOINT_STREAM_COUNT:
            return

        self._request_offboard_and_arm()
        self._command_retry_counter = 0
        self._state = AdapterState.REQUESTING_OFFBOARD

    def _handle_offboard_request(self) -> None:
        """PX4가 Offboard 및 Armed 상태가 될 때까지 확인한다."""
        if self._is_offboard_and_armed():
            self._state = AdapterState.TAKING_OFF
            self.get_logger().info(
                "Offboard mode enabled and vehicle armed."
            )
            self._publish_flight_status("이륙 중: Offboard 및 시동 확인")
            return

        self._command_retry_counter += 1

        if (
            self._command_retry_counter
            < COMMAND_RETRY_INTERVAL_TICKS
        ):
            return

        # UDP 통신에서 명령이 누락될 수 있으므로 PX4 상태가 바뀌지
        # 않았다면 1초 간격으로 모드 전환과 시동을 다시 요청한다.
        self._request_offboard_and_arm()
        self._command_retry_counter = 0

    def _handle_takeoff(self) -> None:
        """수직 이륙을 완료한 뒤 선택한 좌표 방식으로 이동한다."""
        if not self._is_offboard_and_armed():
            self._enter_error(
                "Offboard mode or armed state was lost during takeoff."
            )
            return

        if not self._has_reached_takeoff_altitude():
            return

        # 단순 이륙 명령은 목표 고도에 도달하면 추가 이동 없이
        # 현재 위치와 기수 방향을 유지한다.
        if self._target_mode == TARGET_MODE_TAKEOFF:
            self._state = AdapterState.HOLDING

            self.get_logger().info(
                "Takeoff target reached. "
                "Holding current position and yaw."
            )
            self._publish_flight_status(
                "목표 고도 도달: 호버링 중"
            )
            return

        try:
            mission_target = self._prepare_post_takeoff_target()
        except (
            CoordinateCalculationError,
            RuntimeError,
            ValueError,
        ) as error:
            self._enter_error(
                f"Failed to prepare post-takeoff target: {error}"
            )
            return

        # 수직 이륙이 끝난 후에만 수평 또는 추가 수직 이동 목표로
        # 전환한다. 이 순서를 지켜야 대각선 이륙을 방지할 수 있다.
        self._target_position = mission_target

        if self._target_mode == TARGET_MODE_ROTATION:
            self._state = AdapterState.ROTATING
            self.get_logger().info(
                "Takeoff target reached. Rotating to yaw target."
            )
            self._publish_flight_status("회전 중: 목표 방향으로 기수 변경")
            return

        self._state = AdapterState.MOVING_TO_TARGET
        self.get_logger().info(
            "Takeoff target reached. "
            f"Moving to {self._target_mode} target."
        )
        self._publish_flight_status("이동 중: 목표 위치로 비행")

    def _handle_move_to_target(self) -> None:
        """최종 목표까지 이동하고 도달하면 위치 유지로 전환한다."""
        if not self._is_offboard_and_armed():
            self._enter_error(
                "Offboard mode or armed state was lost while moving."
            )
            return

        if not self._has_reached_target_position():
            return

        position = self._vehicle_local_position
        target = self._target_position

        if position is None or target is None:
            self._enter_error(
                "Position data was lost after reaching target."
            )
            return

        position_error_m = math.dist(
            (
                float(position.x),
                float(position.y),
                float(position.z),
            ),
            target,
        )

        # 목표에 도달한 순간의 실제 좌표와 목표 좌표를 함께 기록한다.
        # 반복 타이머에서는 출력하지 않아 로그가 과도하게 쌓이지 않는다.
        self.get_logger().info(
            "Coordinate target reached: "
            "frame=PX4 local NED, "
            f"current=({position.x:.2f}, "
            f"{position.y:.2f}, "
            f"{position.z:.2f}), "
            f"target=({target[0]:.2f}, "
            f"{target[1]:.2f}, "
            f"{target[2]:.2f}), "
            f"error_m={position_error_m:.3f}"
        )

        self._state = AdapterState.HOLDING
        self.get_logger().info(
            f"{self._target_mode.capitalize()} target reached. "
            "Holding target position."
        )
        self._publish_flight_status("목표 위치 도달: 호버링 중")

    def _handle_rotation(self) -> None:
        """현재 위치를 유지하면서 목표 yaw까지 회전한다."""
        if not self._is_offboard_and_armed():
            self._enter_error(
                "Offboard mode or armed state was lost while rotating."
            )
            return

        try:
            reached_target_yaw = self._has_reached_target_yaw()
        except YawCalculationError as error:
            self._enter_error(
                f"Failed to evaluate yaw target: {error}"
            )
            return

        if not reached_target_yaw:
            return

        position = self._vehicle_local_position

        if position is None:
            self._enter_error(
                "Position data was lost after reaching yaw target."
            )
            return

        yaw_error_rad = calculate_yaw_error_rad(
            current_yaw_rad=float(position.heading),
            target_yaw_rad=self._target_yaw_rad,
        )

        self.get_logger().info(
            "Yaw target reached: "
            "frame=PX4 local NED, "
            f"current_yaw_rad={position.heading:.3f}, "
            f"target_yaw_rad={self._target_yaw_rad:.3f}, "
            f"error_deg={math.degrees(yaw_error_rad):.2f}"
        )

        self._state = AdapterState.HOLDING
        self.get_logger().info(
            "Rotation target reached. Holding target position and yaw."
        )
        self._publish_flight_status("회전 완료: 호버링 중")

    def _handle_hovering(self) -> None:
        """지정된 호버링 시간이 끝나면 명령 대기로 돌아간다."""
        deadline = self._hover_deadline_monotonic

        if deadline is None:
            self._enter_error(
                "Timed hover deadline is not available."
            )
            return

        if time.monotonic() < deadline:
            return

        self._hover_deadline_monotonic = None
        self._state = AdapterState.HOLDING

        self.get_logger().info(
            "Timed hover completed. "
            "Waiting for the next command."
        )
        self._publish_flight_status(
            "호버링 완료: 다음 명령 대기"
        )

    def _monitor_holding_state(self) -> None:
        """위치 유지 중 PX4 제어 상태가 정상인지 감시한다."""
        if self._is_offboard_and_armed():
            return

        # 자동으로 재시동하면 착륙 요청과 충돌할 수 있으므로
        # 상태를 복구하지 않고 명확한 오류로 처리한다.
        self._enter_error(
            "Offboard mode or armed state was lost while holding."
        )

    def _handle_landing(self) -> None:
        """PX4 착륙 진행 상태를 감시하고 Disarm 완료를 확인한다."""
        status = self._vehicle_status

        if status is None:
            return

        if is_vehicle_disarmed(status):
            self._target_position = None
            self._mission_target_position = None
            self._coordinate_calculator = None
            self._command_retry_counter = 0
            self._state = AdapterState.LANDED

            self.get_logger().info(
                "Landing completed. Vehicle is disarmed."
            )
            self._publish_flight_status(
                "착륙 완료: 시동 해제 확인"
            )
            return

        # PX4가 착륙 명령을 처리하기 전까지 여전히 Offboard라면
        # Offboard 소실로 인한 급격한 Failsafe 전환을 막기 위해
        # 기존 위치 세트포인트를 계속 발행한다.
        if (
            status.nav_state
            == VehicleStatus.NAVIGATION_STATE_OFFBOARD
        ):
            self._publish_offboard_control_mode()
            self._publish_target_position()

        self._command_retry_counter += 1

        if (
            self._command_retry_counter
            < COMMAND_RETRY_INTERVAL_TICKS
        ):
            return

        # UDP에서 첫 착륙 명령이 유실될 가능성에 대비해
        # Disarm 완료 전까지 1초 간격으로 착륙을 다시 요청한다.
        self._request_land()
        self._command_retry_counter = 0

    def _has_reached_takeoff_altitude(self) -> bool:
        """현재 고도가 목표 고도 허용 오차 안인지 확인한다."""
        position = self._vehicle_local_position
        target = self._target_position

        if position is None or target is None:
            return False

        if not position.z_valid:
            return False

        return has_reached_altitude(
            current_z_m=float(position.z),
            target_z_m=target[2],
            tolerance_m=TAKEOFF_ALTITUDE_TOLERANCE_M,
        )

    def _has_reached_target_position(self) -> bool:
        """현재 위치가 최종 목표의 허용 거리 안인지 확인한다."""
        position = self._vehicle_local_position
        target = self._target_position

        if position is None or target is None:
            return False

        if not position.xy_valid or not position.z_valid:
            return False

        return has_reached_position(
            current_position=(
                float(position.x),
                float(position.y),
                float(position.z),
            ),
            target_position=target,
            tolerance_m=TARGET_POSITION_TOLERANCE_M,
        )

    def _has_reached_target_yaw(self) -> bool:
        """현재 기수 방향이 목표 yaw 허용 오차 안인지 확인한다."""
        position = self._vehicle_local_position

        if position is None:
            return False

        return has_reached_yaw(
            current_yaw_rad=float(position.heading),
            target_yaw_rad=self._target_yaw_rad,
            tolerance_deg=TARGET_YAW_TOLERANCE_DEG,
        )

    def _is_offboard_and_armed(self) -> bool:
        """PX4가 Offboard 비행 모드이며 시동 상태인지 확인한다."""
        return is_offboard_and_armed(self._vehicle_status)

    def _request_offboard_and_arm(self) -> None:
        """PX4에 Offboard 모드 전환과 시동을 요청한다."""
        self._publish_vehicle_command(
            command=VehicleCommand.VEHICLE_CMD_DO_SET_MODE,
            param1=PX4_CUSTOM_MAIN_MODE,
            param2=PX4_OFFBOARD_SUB_MODE,
        )
        self._publish_vehicle_command(
            command=VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM,
            param1=1.0,
        )

        self.get_logger().info(
            "Requested Offboard mode and vehicle arm."
        )

    def _request_land(self) -> None:
        """PX4에 현재 위치 자동 착륙을 요청한다."""
        self._publish_vehicle_command(
            command=VehicleCommand.VEHICLE_CMD_NAV_LAND,
        )

        self.get_logger().info(
            "Requested PX4 automatic landing."
        )

    def _publish_offboard_control_mode(self) -> None:
        """위치 기반 Offboard 제어 모드를 발행한다."""
        message = OffboardControlMode()
        message.timestamp = self._timestamp_microseconds()
        message.position = True
        message.velocity = False
        message.acceleration = False
        message.attitude = False
        message.body_rate = False
        message.thrust_and_torque = False
        message.direct_actuator = False

        self._offboard_control_mode_publisher.publish(message)

    def _publish_target_position(self) -> None:
        """현재 비행 단계의 목표 위치를 PX4에 발행한다."""
        target = self._target_position

        if target is None:
            return

        message = TrajectorySetpoint()
        message.timestamp = self._timestamp_microseconds()
        message.position = [
            target[0],
            target[1],
            target[2],
        ]
        message.yaw = self._target_yaw_rad

        self._trajectory_setpoint_publisher.publish(message)

    def _publish_vehicle_command(
        self,
        command: int,
        param1: float = 0.0,
        param2: float = 0.0,
    ) -> None:
        """PX4 VehicleCommand 메시지를 생성해 발행한다."""
        message = VehicleCommand()
        message.timestamp = self._timestamp_microseconds()
        message.param1 = param1
        message.param2 = param2
        message.command = command
        message.target_system = PX4_TARGET_SYSTEM_ID
        message.target_component = PX4_TARGET_COMPONENT_ID
        message.source_system = PX4_SOURCE_SYSTEM_ID
        message.source_component = PX4_SOURCE_COMPONENT_ID
        message.from_external = True

        self._vehicle_command_publisher.publish(message)

    def _timestamp_microseconds(self) -> int:
        """현재 ROS 2 시간을 마이크로초 단위로 반환한다."""
        return self.get_clock().now().nanoseconds // 1000


def main(args: list[str] | None = None) -> None:
    """PX4 어댑터 노드를 실행한다."""
    rclpy.init(args=args)
    node = Px4CommandAdapter()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("PX4 adapter stopped by user.")
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
