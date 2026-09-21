"""텍스트 명령을 LLM 서비스에 전달하고 검증된 명령을 발행한다."""

import json
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from drone_command_interface.command_output_parser import (
    InvalidModelOutputError,
)
from drone_llm.command_bridge_logic import CommandBridgeError
from drone_llm.command_bridge_logic import prepare_runtime_command
from llm_ros2.srv import AskLLM


TEXT_COMMAND_TOPIC = "/drone/text_command"
VALIDATED_COMMAND_TOPIC = "/drone/validated_command"
BRIDGE_STATUS_TOPIC = "/drone/command_bridge_status"
LLM_SERVICE_NAME = "/ask_llm"
TOPIC_QUEUE_DEPTH = 10


class CommandBridgeNode(Node):
    """텍스트 입력과 PX4 명령 실행기 사이의 검증 경계다."""

    def __init__(self) -> None:
        super().__init__("command_bridge")
        self._request_in_progress = False
        self._llm_client = self.create_client(AskLLM, LLM_SERVICE_NAME)
        self._command_publisher = self.create_publisher(
            String,
            VALIDATED_COMMAND_TOPIC,
            TOPIC_QUEUE_DEPTH,
        )
        self._status_publisher = self.create_publisher(
            String,
            BRIDGE_STATUS_TOPIC,
            TOPIC_QUEUE_DEPTH,
        )
        self._text_subscription = self.create_subscription(
            String,
            TEXT_COMMAND_TOPIC,
            self._handle_text_command,
            TOPIC_QUEUE_DEPTH,
        )
        self.get_logger().info(
            f"텍스트 명령 대기 중: {TEXT_COMMAND_TOPIC}"
        )

    def _handle_text_command(self, message: String) -> None:
        """새 텍스트 명령을 비동기 LLM 서비스 요청으로 보낸다."""
        question = message.data.strip()
        if not question:
            self.get_logger().warning("빈 텍스트 명령을 거부했습니다.")
            self._publish_status("거부됨: 빈 텍스트 명령입니다.")
            return

        if self._request_in_progress:
            self.get_logger().warning(
                "이전 LLM 요청을 처리 중이므로 새 명령을 거부했습니다."
            )
            self._publish_status("거부됨: 이전 명령을 처리 중입니다.")
            return

        if not self._llm_client.service_is_ready():
            self.get_logger().error("LLM 서비스가 준비되지 않았습니다.")
            self._publish_status("거부됨: LLM 서비스가 준비되지 않았습니다.")
            return

        if self._command_publisher.get_subscription_count() == 0:
            self.get_logger().error(
                "PX4 명령 구독자가 없어 요청을 거부했습니다."
            )
            self._publish_status("거부됨: PX4 어댑터가 연결되지 않았습니다.")
            return

        request = AskLLM.Request()
        request.question = question
        self.get_logger().info(f"LLM 입력: {question}")
        self._request_in_progress = True

        try:
            future = self._llm_client.call_async(request)
            future.add_done_callback(self._handle_llm_response)
        except RuntimeError as error:
            self._request_in_progress = False
            self.get_logger().error(f"LLM 요청 실패: {error}")
            self._publish_status(f"거부됨: LLM 요청 실패: {error}")

    def _handle_llm_response(self, future: Any) -> None:
        """LLM 응답을 검증한 뒤 지원 가능한 명령 하나만 발행한다."""
        self._request_in_progress = False

        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"LLM 서비스 호출 실패: {error}")
            self._publish_status(f"거부됨: LLM 서비스 호출 실패: {error}")
            return

        if response is None:
            self.get_logger().error("LLM 서비스 응답이 비어 있습니다.")
            self._publish_status("거부됨: LLM 서비스 응답이 비어 있습니다.")
            return

        self.get_logger().info(f"LLM 출력: {response.response}")

        try:
            command = prepare_runtime_command(response.response)
        except (InvalidModelOutputError, CommandBridgeError) as error:
            self.get_logger().warning(f"명령 발행 거부: {error}")
            self._publish_status(f"거부됨: {error}")
            return

        if self._command_publisher.get_subscription_count() == 0:
            self.get_logger().error(
                "PX4 명령 구독자가 사라져 명령을 발행하지 않았습니다."
            )
            self._publish_status("거부됨: PX4 어댑터 연결이 끊겼습니다.")
            return

        message = String()
        message.data = json.dumps(command, ensure_ascii=False)
        self._command_publisher.publish(message)
        self.get_logger().info(
            f"검증된 명령 발행: {VALIDATED_COMMAND_TOPIC}, "
            f"payload={message.data}"
        )
        self._publish_status(
            f"PX4 어댑터로 전달됨 (실행 완료 아님): {message.data}"
        )

    def _publish_status(self, status: str) -> None:
        """CLI가 확인할 수 있도록 연결 단계의 결과를 발행한다."""
        message = String()
        message.data = status
        self._status_publisher.publish(message)


def main(args: list[str] | None = None) -> None:
    """명령 연결 노드를 실행한다."""
    rclpy.init(args=args)
    node = CommandBridgeNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("명령 연결 노드를 종료합니다.")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
