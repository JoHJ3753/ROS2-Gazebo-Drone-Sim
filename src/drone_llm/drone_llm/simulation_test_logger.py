"""자연어 드론 명령의 시뮬레이션 실행 결과를 JSONL로 기록한다."""

import json
import math
import time
from datetime import datetime
from pathlib import Path

import rclpy
from px4_msgs.msg import TrajectorySetpoint
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String

from drone_llm.command_bridge_node import BRIDGE_STATUS_TOPIC
from drone_llm.command_bridge_node import LLM_RAW_RESPONSE_TOPIC
from drone_llm.command_bridge_node import TEXT_COMMAND_TOPIC
from drone_llm.command_bridge_node import VALIDATED_COMMAND_TOPIC
from drone_llm.simulation_test_log import JsonlTestWriter
from drone_llm.simulation_test_log import PositionSnapshot
from drone_llm.simulation_test_log import SimulationTestRecord
from drone_llm.simulation_test_log import classify_bridge_failure
from drone_llm.simulation_test_log import calculate_pose_error
from drone_llm.simulation_test_log import is_failure_status
from drone_llm.simulation_test_log import is_success_status
from drone_llm.simulation_test_log import make_run_directory
from drone_llm.simulation_test_log import load_test_cases


NODE_NAME = "simulation_test_logger"
FLIGHT_STATUS_TOPIC = "/drone/flight_status"
VEHICLE_POSITION_TOPIC = "/fmu/out/vehicle_local_position"
TRAJECTORY_SETPOINT_TOPIC = "/fmu/in/trajectory_setpoint"
TOPIC_QUEUE_DEPTH = 10
DEFAULT_OUTPUT_ROOT = "simulation_test_outputs"
DEFAULT_TEST_TIMEOUT_SECONDS = 180.0
TIMEOUT_CHECK_PERIOD_SECONDS = 1.0


class SimulationTestLogger(Node):
    """ROS2 실행 단계와 PX4 좌표를 명령별 JSONL로 기록한다."""

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        output_root = Path(
            str(
                self.declare_parameter(
                    "output_root",
                    DEFAULT_OUTPUT_ROOT,
                ).value
            )
        ).expanduser()
        self._test_timeout_seconds = float(
            self.declare_parameter(
                "test_timeout_seconds",
                DEFAULT_TEST_TIMEOUT_SECONDS,
            ).value
        )
        started_at = datetime.now().astimezone()
        run_directory = make_run_directory(output_root, started_at)
        self._writer = JsonlTestWriter(run_directory)
        self._model_id = str(self.declare_parameter("model_id", "unidentified").value)
        self._model_sha256 = str(self.declare_parameter("model_sha256", "").value)
        self._prompt_version = str(self.declare_parameter("prompt_version", "").value)
        case_file = str(self.declare_parameter("test_cases_file", "").value)
        self._test_cases = load_test_cases(Path(case_file).expanduser()) if case_file else {}
        manifest = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "model_id": self._model_id,
            "model_sha256": self._model_sha256 or None,
            "prompt_version": self._prompt_version or None,
            "test_cases_file": case_file or None,
            "coordinate_frame": "PX4 local NED",
            "note": "목표 좌표는 관측된 최신 trajectory_setpoint이며 실제 PX4 명령 수신 확인은 아님",
        }
        (run_directory / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._current_position: PositionSnapshot | None = None
        self._active_record: SimulationTestRecord | None = None
        self._active_started_monotonic: float | None = None
        self._llm_received_monotonic: float | None = None
        self._bridge_published_monotonic: float | None = None
        self._test_sequence = 0

        self.create_subscription(
            String,
            TEXT_COMMAND_TOPIC,
            self._handle_text_command,
            TOPIC_QUEUE_DEPTH,
        )
        self.create_subscription(
            String,
            LLM_RAW_RESPONSE_TOPIC,
            self._handle_llm_response,
            TOPIC_QUEUE_DEPTH,
        )
        self.create_subscription(
            String,
            VALIDATED_COMMAND_TOPIC,
            self._handle_validated_command,
            TOPIC_QUEUE_DEPTH,
        )
        self.create_subscription(
            String,
            BRIDGE_STATUS_TOPIC,
            self._handle_bridge_status,
            TOPIC_QUEUE_DEPTH,
        )
        self.create_subscription(
            String,
            FLIGHT_STATUS_TOPIC,
            self._handle_flight_status,
            TOPIC_QUEUE_DEPTH,
        )
        self.create_subscription(
            VehicleLocalPosition,
            VEHICLE_POSITION_TOPIC,
            self._handle_vehicle_position,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            TrajectorySetpoint,
            TRAJECTORY_SETPOINT_TOPIC,
            self._handle_target_position,
            qos_profile_sensor_data,
        )
        self.create_timer(
            TIMEOUT_CHECK_PERIOD_SECONDS,
            self._check_timeout,
        )
        self.get_logger().info(
            f"시뮬레이션 테스트 로그 저장: {self._writer.output_path}"
        )

    def _handle_text_command(self, message: String) -> None:
        """새 자연어 명령을 하나의 테스트로 시작한다."""
        if self._active_record is not None:
            self._finish_record(
                result="interrupted",
                failure_stage="test_runner",
                failure_reason=(
                    "이전 테스트 완료 전에 새 명령이 수신됐습니다."
                ),
            )

        self._test_sequence += 1
        now = datetime.now().astimezone()
        input_text = message.data.strip()
        case = self._test_cases.get(input_text, {})
        self._active_record = SimulationTestRecord(
            timestamp=now.isoformat(timespec="milliseconds"),
            test_id=f"SIM-{self._test_sequence:04d}",
            natural_language_input=input_text,
            initial_position=self._copy_current_position(),
            model_id=self._model_id,
            case_id=case.get("case_id"),
            category=case.get("category"),
            expected_status=case.get("expected_status"),
            expected_commands=case.get("expected_commands"),
            expected_runtime=case.get("expected_runtime"),
        )
        self._active_started_monotonic = time.monotonic()
        self._llm_received_monotonic = None
        self._bridge_published_monotonic = None
        self.get_logger().info(
            f"테스트 시작: {self._active_record.test_id}"
        )

    def _handle_llm_response(self, message: String) -> None:
        """LLM 원문 응답을 활성 테스트에 저장한다."""
        if self._active_record is not None:
            self._active_record.llm_raw_response = message.data
            self._llm_received_monotonic = time.monotonic()
            if self._active_started_monotonic is not None:
                self._active_record.llm_latency_seconds = round(
                    self._llm_received_monotonic - self._active_started_monotonic,
                    3,
                )

    def _handle_validated_command(self, message: String) -> None:
        """검증을 통과해 PX4로 전달된 명령을 저장한다."""
        record = self._active_record
        if record is None:
            return

        try:
            command = json.loads(message.data)
        except json.JSONDecodeError as error:
            self._finish_record(
                result="failed",
                failure_stage="bridge",
                failure_reason=f"검증 명령 JSON 파싱 실패: {error}",
            )
            return

        record.parsed_command = command
        record.validation_result = "passed"
        record.bridge_result = "published"
        self._bridge_published_monotonic = time.monotonic()
        if self._llm_received_monotonic is not None:
            record.bridge_latency_seconds = round(
                self._bridge_published_monotonic - self._llm_received_monotonic,
                3,
            )
        record.px4_command = {
            "topic": VALIDATED_COMMAND_TOPIC,
            "payload": command,
        }

    def _handle_bridge_status(self, message: String) -> None:
        """브리지 거부를 실패 결과로 확정한다."""
        record = self._active_record
        if record is None or not message.data.startswith("거부됨"):
            return

        failure_stage, failure_reason = classify_bridge_failure(message.data)
        record.validation_result = "rejected"
        record.bridge_result = "rejected"
        if self._llm_received_monotonic is not None:
            record.bridge_latency_seconds = round(
                time.monotonic() - self._llm_received_monotonic,
                3,
            )
        self._finish_record(
            result="rejected",
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )

    def _handle_flight_status(self, message: String) -> None:
        """PX4 실행 완료 또는 실패 상태를 기록한다."""
        record = self._active_record
        if record is None:
            return

        record.flight_status = message.data
        if is_success_status(message.data):
            self._finish_record(result="success")
        elif is_failure_status(message.data):
            self._finish_record(
                result="failed",
                failure_stage="execution",
                failure_reason=message.data,
            )

    def _handle_vehicle_position(
        self,
        message: VehicleLocalPosition,
    ) -> None:
        """PX4 Local NED의 최신 실제 위치를 저장한다."""
        values = (message.x, message.y, message.z, message.heading)
        if not all(math.isfinite(value) for value in values):
            return
        self._current_position = PositionSnapshot(
            x=float(message.x),
            y=float(message.y),
            z=float(message.z),
            yaw_rad=float(message.heading),
        )

    def _handle_target_position(
        self,
        message: TrajectorySetpoint,
    ) -> None:
        """활성 명령 중 PX4에 발행된 최신 목표 위치를 저장한다."""
        record = self._active_record
        if record is None or record.bridge_result != "published":
            return
        x, y, z = message.position
        if not all(math.isfinite(value) for value in (x, y, z)):
            return
        yaw_rad = float(message.yaw)
        if not math.isfinite(yaw_rad):
            yaw_rad = 0.0
        record.target_position = PositionSnapshot(
            x=float(x),
            y=float(y),
            z=float(z),
            yaw_rad=yaw_rad,
        )

    def _check_timeout(self) -> None:
        """완료되지 않은 테스트를 제한 시간 후 종료한다."""
        if (
            self._active_record is None
            or self._active_started_monotonic is None
        ):
            return
        elapsed_seconds = time.monotonic() - self._active_started_monotonic
        if elapsed_seconds < self._test_timeout_seconds:
            return
        self._finish_record(
            result="timeout",
            failure_stage="timeout",
            failure_reason=(
                f"{self._test_timeout_seconds:.1f}초 안에 완료 상태가 "
                "수신되지 않았습니다."
            ),
        )

    def _finish_record(
        self,
        result: str,
        failure_stage: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """활성 테스트를 완료하고 JSONL 한 줄로 저장한다."""
        record = self._active_record
        started_monotonic = self._active_started_monotonic
        if record is None or started_monotonic is None:
            return

        record.final_position = self._copy_current_position()
        if self._bridge_published_monotonic is not None:
            record.flight_latency_seconds = round(
                time.monotonic() - self._bridge_published_monotonic,
                3,
            )
        record.elapsed_seconds = round(
            time.monotonic() - started_monotonic,
            3,
        )
        record.result = result
        record.failure_stage = failure_stage
        record.failure_reason = failure_reason
        calculate_pose_error(record)
        self._writer.append(record)
        self.get_logger().info(
            f"테스트 저장 완료: {record.test_id}, result={result}"
        )
        self._active_record = None
        self._active_started_monotonic = None
        self._llm_received_monotonic = None
        self._bridge_published_monotonic = None

    def _copy_current_position(self) -> PositionSnapshot | None:
        """변경 가능한 최신 좌표를 독립적인 값 객체로 복사한다."""
        position = self._current_position
        if position is None:
            return None
        return PositionSnapshot(
            x=position.x,
            y=position.y,
            z=position.z,
            yaw_rad=position.yaw_rad,
        )


def main(args: list[str] | None = None) -> None:
    """시뮬레이션 테스트 로거 노드를 실행한다."""
    rclpy.init(args=args)
    node = SimulationTestLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("시뮬레이션 테스트 로거를 종료합니다.")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
