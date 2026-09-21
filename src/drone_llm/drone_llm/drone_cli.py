"""터미널에서 자연어 드론 명령을 반복 입력하는 ROS 2 클라이언트."""

import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from drone_llm.command_bridge_node import BRIDGE_STATUS_TOPIC
from drone_llm.command_bridge_node import TEXT_COMMAND_TOPIC


TOPIC_QUEUE_DEPTH = 10
STATUS_TIMEOUT_SECONDS = 130.0
ROS_SPIN_TIMEOUT_SECONDS = 0.1
EXIT_COMMANDS = frozenset({"exit", "quit", "종료"})


class DroneCli(Node):
    """입력 문장을 연결 노드에 보내고 결과를 터미널에 보여준다."""

    def __init__(self) -> None:
        super().__init__("drone_cli")
        self._last_status: str | None = None
        self._text_publisher = self.create_publisher(
            String,
            TEXT_COMMAND_TOPIC,
            TOPIC_QUEUE_DEPTH,
        )
        self._status_subscription = self.create_subscription(
            String,
            BRIDGE_STATUS_TOPIC,
            self._handle_status,
            TOPIC_QUEUE_DEPTH,
        )

    def _handle_status(self, message: String) -> None:
        """연결 노드의 최신 결과를 저장한다."""
        self._last_status = message.data

    def send_command(self, question: str) -> str:
        """문장을 발행하고 연결 단계의 결과를 기다린다."""
        if self._text_publisher.get_subscription_count() == 0:
            return "연결 노드가 실행 중이지 않습니다."

        self._last_status = None
        message = String()
        message.data = question
        self._text_publisher.publish(message)

        deadline = time.monotonic() + STATUS_TIMEOUT_SECONDS
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=ROS_SPIN_TIMEOUT_SECONDS)
            if self._last_status is not None:
                return self._last_status

        return "응답 대기 시간이 초과됐습니다. 실행 여부는 로그에서 확인하세요."


def main(args: list[str] | None = None) -> None:
    """종료 명령이나 Ctrl+C를 받을 때까지 텍스트 명령을 입력받는다."""
    rclpy.init(args=args)
    node = DroneCli()

    try:
        sys.stdout.write("자연어 드론 명령을 입력하세요. 종료: exit\n")
        while rclpy.ok():
            question = input("명령 > ").strip()
            if question.lower() in EXIT_COMMANDS:
                break
            if not question:
                continue

            status = node.send_command(question)
            sys.stdout.write(f"{status}\n")
            sys.stdout.flush()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write("\n")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
