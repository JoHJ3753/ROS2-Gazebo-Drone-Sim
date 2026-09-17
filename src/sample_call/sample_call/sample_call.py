import time
from pathlib import Path

import rclpy
from rclpy.node import Node

from llama_cpp import Llama

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

        # yaml(파라미터 서버)에서 값 읽기. 기본값은 qwen.yaml에 없을 때만 사용됨.
        self.declare_parameter(
            "model_path",
            DEFAULT_MODEL_PATH,
        )
        self.declare_parameter("context_size", 2048)
        self.declare_parameter("threads", 4)
        self.declare_parameter("max_tokens", 512)
        self.declare_parameter("temperature", 0.2)
        self.declare_parameter("timeout_seconds", 120)  # 아직 로직에는 미사용
        self.declare_parameter("system_prompt", (
            "너는 한국어로 대화하는 AI 어시스턴트이다.\n\n"
            "규칙:\n"
            "1. 모든 답변은 반드시 한국어로만 작성한다.\n"
            "2. 중국어, 일본어, 영어 등 다른 언어를 사용하지 않는다.\n"
            "3. 한자(漢字)를 사용하지 않는다.\n"
            "4. 사용자가 다른 언어로 질문하더라도 한국어로 답변한다.\n"
            "5. 사용자의 질문을 정확하게 이해하고 답변한다.\n"
            "6. 모르는 내용은 추측하지 않고 모른다고 답한다.\n"
            "7. 답변은 이해하기 쉽고 명확하게 작성한다."
        ))

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

        system_prompt = self.get_parameter("system_prompt").value
        max_tokens = self.get_parameter("max_tokens").value
        temperature = self.get_parameter("temperature").value

        messages = [
            {
                "role": "system",
                "content": system_prompt
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
