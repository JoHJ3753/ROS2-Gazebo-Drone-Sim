import time
from pathlib import Path

import rclpy
from rclpy.node import Node

from llama_cpp import Llama

from drone_command_interface.prompts import SYSTEM_PROMPT
from llm_ros2.srv import AskLLM


DEFAULT_MODEL_PATH = "model/Qwen2.5-3B-Instruct-Q4_K_M.gguf"


def resolve_model_path(model_path: str) -> Path:
    """Resolve an absolute path or a path relative to the project root."""
    path = Path(model_path).expanduser()

    if path.is_absolute():
        return path.resolve()

    search_roots = (Path.cwd(), *Path(__file__).resolve().parents)
    for search_root in search_roots:
        candidate = search_root / path
        if candidate.is_file():
            return candidate.resolve()

    return (Path.cwd() / path).resolve()


class LLMService(Node):

    def __init__(self):
        super().__init__("llm_service")

        # YAML 파라미터가 없을 때만 아래 기본값을 사용한다.
        self.declare_parameter(
            "model_path",
            DEFAULT_MODEL_PATH,
        )
        self.declare_parameter("context_size", 16384)
        self.declare_parameter("threads", 4)
        self.declare_parameter("max_tokens", 256)
        self.declare_parameter("temperature", 0.0)
        self.declare_parameter("timeout_seconds", 120)  # 아직 로직에는 미사용

        model_path_parameter = self.get_parameter("model_path").value
        model_path = resolve_model_path(model_path_parameter)
        context_size = self.get_parameter("context_size").value
        threads = self.get_parameter("threads").value

        if not model_path.is_file():
            error_message = f"모델 파일을 찾을 수 없습니다: {model_path}"
            self.get_logger().error(error_message)
            raise FileNotFoundError(error_message)

        self.get_logger().info(f"모델 로딩 중: {model_path}")

        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=context_size,
            n_threads=threads,
            verbose=False
        )

        self.get_logger().info("모델 로딩 완료!")

        self.service = self.create_service(
            AskLLM,
            "ask_llm",
            self.handle_request
        )

        self.get_logger().info(
            "LLM Service 준비 완료: /ask_llm"
        )

    def handle_request(self, request, response):

        question = request.question

        self.get_logger().info(
            f"질문 수신: {question}"
        )

        self.get_logger().info(
            "입력 데이터 처리 중..."
        )

        max_tokens = self.get_parameter("max_tokens").value
        temperature = self.get_parameter("temperature").value

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": question
            }
        ]

        self.get_logger().info(
            "LLM 응답 생성 중... 잠시만 기다려주세요."
        )

        start_time = time.time()

        output = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )

        elapsed_time = time.time() - start_time

        self.get_logger().info(
            f"LLM 응답 생성 완료! ({elapsed_time:.2f}초)"
        )

        answer = output["choices"][0]["message"]["content"]

        response.response = answer

        self.get_logger().info(
            f"응답: {answer}"
        )

        return response


def main(args=None):

    rclpy.init(args=args)

    node = LLMService()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
