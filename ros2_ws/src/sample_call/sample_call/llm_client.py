import sys

import rclpy
from rclpy.node import Node

from llm_ros2.srv import AskLLM


class LLMClient(Node):

    def __init__(self):
        super().__init__("llm_client")

        self.client = self.create_client(
            AskLLM,
            "ask_llm"
        )

        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info(
                "LLM Service를 기다리는 중..."
            )

    def ask(self, question):

        request = AskLLM.Request()

        request.question = question

        future = self.client.call_async(request)

        rclpy.spin_until_future_complete(
            self,
            future
        )

        return future.result().response


def main(args=None):

    rclpy.init(args=args)

    node = LLMClient()

    question = "철수는 영희보다 키가 크고, 영희는 민수보다 키가 크다. 가장 키가 작은 사람은 누구인가?"

    response = node.ask(question)

    print("\n===== LLM 응답 =====")
    print(response)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()