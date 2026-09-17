"""학습된 LoRA 어댑터로 드론 자연어 명령을 추론한다."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM
from transformers import AutoTokenizer


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DRONE_INTERFACE_SOURCE = (
    REPOSITORY_ROOT / "src" / "drone_command_interface"
)

if str(DRONE_INTERFACE_SOURCE) not in sys.path:
    sys.path.insert(0, str(DRONE_INTERFACE_SOURCE))

from drone_command_interface.command_output_parser import (  # noqa: E402
    InvalidModelOutputError,
)
from drone_command_interface.command_output_parser import (  # noqa: E402
    parse_command_output,
)
from drone_command_interface.prompts import SYSTEM_PROMPT  # noqa: E402


DEFAULT_MODEL_PATH = Path("/home/work/models/qwen2.5-3b-instruct")
DEFAULT_ADAPTER_PATH = (
    REPOSITORY_ROOT
    / "training"
    / "outputs"
    / "2026-09-17_142025"
    / "adapter"
)
DEFAULT_MAX_NEW_TOKENS = 256
EXIT_COMMANDS = {"exit", "quit", "종료"}

LOGGER = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """추론 실행 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Qwen2.5 드론 명령 LoRA 추론",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="변환할 드론 자연어 명령",
    )
    parser.add_argument(
        "--model-name",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help="Qwen 원본 모델 경로",
    )
    parser.add_argument(
        "--adapter-path",
        type=Path,
        default=DEFAULT_ADAPTER_PATH,
        help="학습된 LoRA 어댑터 경로",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=DEFAULT_MAX_NEW_TOKENS,
    )
    return parser.parse_args()


def validate_paths(
    model_path: Path,
    adapter_path: Path,
) -> None:
    """원본 모델과 LoRA 어댑터 경로를 검증한다."""
    if not model_path.is_dir():
        raise FileNotFoundError(
            f"원본 모델 폴더를 찾을 수 없습니다: {model_path}"
        )

    if not adapter_path.is_dir():
        raise FileNotFoundError(
            f"LoRA 어댑터 폴더를 찾을 수 없습니다: {adapter_path}"
        )

    adapter_config_path = adapter_path / "adapter_config.json"
    adapter_model_path = adapter_path / "adapter_model.safetensors"

    if not adapter_config_path.is_file():
        raise FileNotFoundError(
            f"LoRA 설정 파일을 찾을 수 없습니다: {adapter_config_path}"
        )

    if not adapter_model_path.is_file():
        raise FileNotFoundError(
            f"LoRA 가중치 파일을 찾을 수 없습니다: {adapter_model_path}"
        )


def load_model(
    model_path: Path,
    adapter_path: Path,
) -> tuple[Any, Any]:
    """원본 Qwen 모델에 LoRA 어댑터를 연결한다."""
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA GPU를 사용할 수 없습니다. KT Cloud A100에서 실행하세요."
        )

    tokenizer = AutoTokenizer.from_pretrained(adapter_path)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    tokenizer.padding_side = "right"

    LOGGER.info("원본 모델을 불러옵니다: %s", model_path)
    base_model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        attn_implementation="eager",
    )
    base_model.to("cuda")

    LOGGER.info("LoRA 어댑터를 연결합니다: %s", adapter_path)
    model = PeftModel.from_pretrained(
        base_model,
        adapter_path,
    )
    model.eval()

    LOGGER.info("모델 준비가 완료됐습니다.")
    return model, tokenizer


@torch.inference_mode()
def generate_command(
    user_command: str,
    model: Any,
    tokenizer: Any,
    max_new_tokens: int,
) -> str:
    """자연어 명령을 드론 명령 JSON 문자열로 변환한다."""
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_command,
        },
    ]

    model_inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )
    model_inputs = {
        key: value.to(model.device)
        for key, value in model_inputs.items()
    }

    generated_tokens = model.generate(
        **model_inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        temperature=None,
        top_p=None,
        top_k=None,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )

    prompt_length = model_inputs["input_ids"].shape[-1]
    response_tokens = generated_tokens[0][prompt_length:]

    return tokenizer.decode(
        response_tokens,
        skip_special_tokens=True,
    ).strip()


def parse_and_validate_response(
    raw_response: str,
) -> dict[str, Any]:
    """
    모델 원문을 공용 명령 파서로 검증한다.

    공용 파서를 사용해 ROS 2 실행 경로와 LoRA 평가 경로가
    동일한 JSON 및 Function Schema 규칙을 적용하도록 한다.
    """
    try:
        return parse_command_output(raw_response)
    except InvalidModelOutputError as error:
        raise InvalidModelOutputError(
            f"LoRA inference output was rejected: {error}"
        ) from error


def run_inference(
    user_command: str,
    model: Any,
    tokenizer: Any,
    max_new_tokens: int,
) -> None:
    """명령 하나를 추론하고 검증 결과를 출력한다."""
    LOGGER.info("사용자 명령: %s", user_command)

    raw_response = generate_command(
        user_command=user_command,
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=max_new_tokens,
    )
    LOGGER.info("LLM 원본 응답: %s", raw_response)

    try:
        parsed_response = parse_and_validate_response(raw_response)
    except InvalidModelOutputError as error:
        # 검증에 실패한 출력은 화면에만 기록하고
        # 이후 PX4 실행 계층으로 전달하지 않는다.
        LOGGER.error(
            "LLM 출력 검증 실패: %s",
            error,
        )
        return

    command_names = [
        command["name"]
        for command in parsed_response["commands"]
    ]

    # 강사님 요청에 따라 검증된 상태와 명령값도 로그로 기록한다.
    LOGGER.info(
        "LLM 출력 검증 성공: status=%s, commands=%s",
        parsed_response["status"],
        command_names,
    )
    print(
        json.dumps(
            parsed_response,
            ensure_ascii=False,
            indent=2,
        )
    )


def run_interactive_mode(
    model: Any,
    tokenizer: Any,
    max_new_tokens: int,
) -> None:
    """종료 명령이 입력될 때까지 대화형 추론을 반복한다."""
    print("드론 명령을 입력하세요. 종료하려면 '종료'를 입력하세요.")

    while True:
        try:
            user_command = input("\n명령> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n추론을 종료합니다.")
            return

        if user_command.lower() in EXIT_COMMANDS:
            print("추론을 종료합니다.")
            return

        if not user_command:
            LOGGER.warning("빈 명령은 처리할 수 없습니다.")
            continue

        run_inference(
            user_command=user_command,
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=max_new_tokens,
        )


def main() -> None:
    """학습된 어댑터를 사용하는 추론 프로그램을 실행한다."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    arguments = parse_arguments()

    model_path = arguments.model_name.expanduser().resolve()
    adapter_path = arguments.adapter_path.expanduser().resolve()

    try:
        validate_paths(model_path, adapter_path)
        model, tokenizer = load_model(
            model_path=model_path,
            adapter_path=adapter_path,
        )
    except (FileNotFoundError, RuntimeError) as error:
        LOGGER.error("%s", error)
        raise SystemExit(1) from error

    if arguments.command:
        run_inference(
            user_command=arguments.command,
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=arguments.max_new_tokens,
        )
        return

    run_interactive_mode(
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=arguments.max_new_tokens,
    )


if __name__ == "__main__":
    main()
