"""PX4 Offboard 통신을 담당하는 ROS 2 어댑터 노드."""

from enum import Enum
import math

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

from drone_control.coordinate_calculator import CoordinateCalculationError
from drone_control.coordinate_calculator import CoordinateCalculator
from drone_control.coordinate_calculator import NedPosition


# 이 파일의 첫 번째 버전은 Gazebo 시뮬레이션 검증용이다.
# 실제 기체에 적용하기 전에는 별도의 안전 검증이 필요하다.
NODE_NAME = "px4_command_adapter"

CONTROL_PERIOD_SECONDS = 0.1
SETPOINT_STREAM_COUNT = 20
COMMAND_RETRY_INTERVAL_TICKS = 10

DEFAULT_TAKEOFF_HEIGHT_M = 2.0
DEFAULT_TARGET_NORTH_M = 1.0
DEFAULT_TARGET_EAST_M = 0.0
DEFAULT_TARGET_ALTITUDE_M = 2.0

TAKEOFF_ALTITUDE_TOLERANCE_M = 0.15
TARGET_POSITION_TOLERANCE_M = 0.2
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
    """위치와 이륙 전 검사 결과가 제어 가능한 상태인지 확인한다."""
    if position is None or status is None:
        return False

    if not position.xy_valid or not position.z_valid:
        return False

    return status.pre_flight_checks_pass


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


class AdapterState(Enum):
    """PX4 어댑터의 절대좌표 이동 상태를 정의한다."""

    WAITING_FOR_READY = "waiting_for_ready"
    STREAMING_SETPOINTS = "streaming_setpoints"
    REQUESTING_OFFBOARD = "requesting_offboard"
    TAKING_OFF = "taking_off"
    MOVING_TO_TARGET = "moving_to_target"
    HOLDING = "holding"
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

        self._state = AdapterState.WAITING_FOR_READY
        self._vehicle_local_position: VehicleLocalPosition | None = None
        self._vehicle_status: VehicleStatus | None = None

        # _target_position은 현재 PX4에 전송하는 목표다.
        # 이륙 중에는 수직 이륙 목표이고, 이륙 완료 후에는
        # 최종 절대좌표 목표로 교체된다.
        self._target_position: tuple[float, float, float] | None = None

        # 최종 절대좌표 목표는 이륙 목표와 구분해 보관한다.
        self._mission_target_position: (
            tuple[float, float, float] | None
        ) = None

        self._target_yaw_rad = 0.0

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

    def _vehicle_status_callback(
        self,
        message: VehicleStatus,
    ) -> None:
        """PX4의 최신 시동 상태와 비행 모드를 저장한다."""
        self._vehicle_status = message

    def _timer_callback(self) -> None:
        """현재 상태에 따라 이륙과 절대좌표 이동 절차를 진행한다."""
        if self._state is AdapterState.WAITING_FOR_READY:
            if not self._is_vehicle_ready():
                return

            try:
                self._prepare_mission_targets(
                    DEFAULT_TAKEOFF_HEIGHT_M
                )
            except (
                CoordinateCalculationError,
                RuntimeError,
                ValueError,
            ) as error:
                # 잘못된 좌표가 PX4로 전달되기 전에 실행을 중단한다.
                self._state = AdapterState.ERROR
                self.get_logger().error(
                    f"Failed to prepare mission target: {error}"
                )
                return

            self._state = AdapterState.STREAMING_SETPOINTS

            self.get_logger().info(
                "Vehicle data is valid. Starting setpoint stream."
            )

        if self._state is AdapterState.ERROR:
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

        if self._state is AdapterState.HOLDING:
            self._monitor_holding_state()

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
        홈 위치를 저장하고 이륙 목표와 절대좌표 목표를 준비한다.

        모든 좌표를 이륙 전에 검증해 잘못된 목표값이 입력된 경우
        PX4의 Offboard 전환과 시동이 시작되지 않도록 한다.
        """
        position = self._vehicle_local_position

        if position is None:
            raise RuntimeError(
                "Vehicle position is required to prepare mission"
            )

        # 좌표를 어느 토픽과 좌표계에서 읽었는지 기록한다.
        # 이 로그를 통해 PX4가 전달한 원본 좌표를 확인할 수 있다.
        self.get_logger().info(
            "Coordinate source: "
            "topic=/fmu/out/vehicle_local_position, "
            "frame=PX4 local NED, "
            f"x={position.x:.2f}, "
            f"y={position.y:.2f}, "
            f"z={position.z:.2f}"
        )

        # 아직 LLM과 실행기가 연결되지 않았으므로 현재는
        # ROS 2 파라미터에서 읽은 임무 좌표를 기록한다.
        self.get_logger().info(
            "Coordinate command input: "
            "source=ROS 2 parameters, "
            "frame=home-relative, "
            f"north_m={self._target_north_m:.2f}, "
            f"east_m={self._target_east_m:.2f}, "
            f"altitude_m={self._target_altitude_m:.2f}"
        )

        coordinate_calculator = CoordinateCalculator(
            NedPosition(
                north_m=position.x,
                east_m=position.y,
                down_m=position.z,
            )
        )

        mission_target = (
            coordinate_calculator.calculate_absolute_target(
                north_m=self._target_north_m,
                east_m=self._target_east_m,
                altitude_m=self._target_altitude_m,
            )
        )

        # 먼저 현재 x와 y를 유지하는 수직 이륙 목표를 만든다.
        self._prepare_takeoff_target(takeoff_height_m)

        # 이륙 완료 후 사용할 홈 기준 절대좌표 목표를 별도로 저장한다.
        self._mission_target_position = mission_target.as_px4_tuple()

        # 사용자 기준 좌표가 실제 PX4 NED 좌표로 어떻게 변환됐는지
        # 기록해 좌표계 또는 부호 오류를 쉽게 확인할 수 있게 한다.
        self.get_logger().info(
            "Coordinate conversion result: "
            "frame=PX4 local NED, "
            f"x={mission_target.north_m:.2f}, "
            f"y={mission_target.east_m:.2f}, "
            f"z={mission_target.down_m:.2f}"
        )

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
        """수직 이륙을 완료한 뒤 절대좌표 이동을 시작한다."""
        if not self._is_offboard_and_armed():
            self._state = AdapterState.ERROR
            self.get_logger().error(
                "Offboard mode or armed state was lost during takeoff."
            )
            return

        if not self._has_reached_takeoff_altitude():
            return

        mission_target = self._mission_target_position

        if mission_target is None:
            self._state = AdapterState.ERROR
            self.get_logger().error(
                "Absolute mission target is not available."
            )
            return

        # 수직 이륙이 끝난 후에만 수평 좌표가 포함된 목표로 바꾼다.
        # 이 순서를 지켜야 출발 지점에서 대각선으로 이륙하지 않는다.
        self._target_position = mission_target
        self._state = AdapterState.MOVING_TO_TARGET

        self.get_logger().info(
            "Takeoff target reached. Moving to absolute target."
        )

    def _handle_move_to_target(self) -> None:
        """절대좌표 목표까지 이동하고 도달하면 위치 유지로 전환한다."""
        if not self._is_offboard_and_armed():
            self._state = AdapterState.ERROR
            self.get_logger().error(
                "Offboard mode or armed state was lost while moving."
            )
            return

        if not self._has_reached_target_position():
            return

        position = self._vehicle_local_position
        target = self._target_position

        if position is None or target is None:
            self._state = AdapterState.ERROR
            self.get_logger().error(
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
            "Absolute target reached. Holding target position."
        )

    def _monitor_holding_state(self) -> None:
        """위치 유지 중 PX4 제어 상태가 정상인지 감시한다."""
        if self._is_offboard_and_armed():
            return

        # 자동으로 재시동하면 착륙 요청과 충돌할 수 있으므로
        # 상태를 복구하지 않고 명확한 오류로 처리한다.
        self._state = AdapterState.ERROR
        self.get_logger().error(
            "Offboard mode or armed state was lost while holding."
        )

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
