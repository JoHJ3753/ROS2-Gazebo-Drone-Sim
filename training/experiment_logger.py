"""학습 실험 환경과 결과를 재현 가능한 형태로 기록한다."""

import json
import logging
import platform
import subprocess
from pathlib import Path
from typing import Any


LOGGER_NAME = "drone_fine_tuning"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"


def configure_experiment_logger(log_path: Path) -> logging.Logger:
    """콘솔과 TXT 파일에 동시에 기록하는 실험 Logger를 생성한다."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_git_commit(repository_root: Path) -> str:
    """현재 저장소의 Git 커밋 해시를 반환한다."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"

    return result.stdout.strip()


def collect_environment_info(repository_root: Path) -> dict[str, Any]:
    """재현성 기록에 필요한 실행 환경 정보를 수집한다."""
    import datasets
    import peft
    import torch
    import transformers

    gpu_name = "not available"
    cuda_version = torch.version.cuda or "not available"

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)

    return {
        "git_commit": get_git_commit(repository_root),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "gpu": gpu_name,
        "cuda_version": cuda_version,
        "pytorch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "datasets_version": datasets.__version__,
        "peft_version": peft.__version__,
    }


def log_mapping(
    logger: logging.Logger,
    title: str,
    values: dict[str, Any],
) -> None:
    """딕셔너리를 사람이 읽기 쉬운 형태로 로그에 기록한다."""
    logger.info("[%s]", title)
    for key, value in values.items():
        logger.info("%s: %s", key, value)


def write_json(path: Path, value: Any) -> None:
    """값을 UTF-8 JSON 파일로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
