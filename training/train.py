"""Qwen2.5-3B-Instruct 드론 명령 LoRA 학습을 실행한다."""

import argparse
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from datasets import Dataset
from datasets import load_dataset
from peft import LoraConfig
from peft import get_peft_model
from transformers import AutoModelForCausalLM
from transformers import AutoTokenizer
from transformers import DataCollatorForSeq2Seq
from transformers import Trainer
from transformers import TrainerCallback
from transformers import TrainingArguments


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DRONE_INTERFACE_SOURCE = (
    REPOSITORY_ROOT / "src" / "drone_command_interface"
)
if str(DRONE_INTERFACE_SOURCE) not in sys.path:
    sys.path.insert(0, str(DRONE_INTERFACE_SOURCE))

from drone_command_interface.prompts import SYSTEM_PROMPT  # noqa: E402
from drone_command_interface.schemas import DRONE_COMMAND_SCHEMA  # noqa: E402
from training.evaluate import evaluate_model  # noqa: E402
from training.evaluate import load_jsonl  # noqa: E402
from training.evaluate import select_failures  # noqa: E402
from training.evaluate import validate_dataset_samples  # noqa: E402
from training.evaluate import write_comparison_report  # noqa: E402
from training.evaluate import write_jsonl  # noqa: E402
from training.experiment_logger import collect_environment_info  # noqa: E402
from training.experiment_logger import configure_experiment_logger  # noqa: E402
from training.experiment_logger import log_mapping  # noqa: E402
from training.experiment_logger import write_json  # noqa: E402


DEFAULT_MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_DATASET_DIRECTORY = REPOSITORY_ROOT / "data" / "dataset_v0.1"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "training" / "outputs"

DEFAULT_EPOCHS = 3.0
DEFAULT_LEARNING_RATE = 2e-4
DEFAULT_BATCH_SIZE = 2
DEFAULT_GRADIENT_ACCUMULATION_STEPS = 8
# 현재 SYSTEM_PROMPT에는 명령 규칙과 전체 JSON Schema가 포함되어 있다.
# 정답 구간이 잘리지 않도록 컨텍스트 범위 안에서 여유를 둔다.
DEFAULT_MAX_SEQUENCE_LENGTH = 16384
DEFAULT_MAX_NEW_TOKENS = 256
DEFAULT_RANDOM_SEED = 42

LORA_RANK = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]


class TrainerLogCallback(TrainerCallback):
    """Transformers Trainer의 수치 로그를 TXT Logger로 전달한다."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def on_log(
        self,
        args: TrainingArguments,
        state: Any,
        control: Any,
        logs: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> None:
        """Step, loss, 평가 결과를 한 줄로 기록한다."""
        del args, control, kwargs
        if not logs:
            return

        values = " | ".join(
            f"{key}={value}"
            for key, value in sorted(logs.items())
        )
        self._logger.info("trainer_step=%s | %s", state.global_step, values)


def parse_arguments() -> argparse.Namespace:
    """학습 실행 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Qwen2.5 드론 명령 LoRA 학습",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIRECTORY,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument("--epochs", type=float, default=DEFAULT_EPOCHS)
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=DEFAULT_LEARNING_RATE,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=DEFAULT_GRADIENT_ACCUMULATION_STEPS,
    )
    parser.add_argument(
        "--max-sequence-length",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_LENGTH,
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=DEFAULT_MAX_NEW_TOKENS,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument(
        "--skip-baseline-evaluation",
        action="store_true",
        help="개발용 옵션. 발표용 본 실험에서는 사용하지 않는다.",
    )
    return parser.parse_args()


def set_random_seed(seed: int) -> None:
    """Python, NumPy, PyTorch의 난수 시드를 고정한다."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_run_directory(output_root: Path) -> Path:
    """현재 시각으로 중복되지 않는 실험 디렉터리를 만든다."""
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_directory = output_root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def load_and_validate_datasets(
    dataset_directory: Path,
) -> tuple[Dataset, Dataset, list[dict[str, Any]]]:
    """세 Dataset split을 읽고 현재 Function Schema로 검증한다."""
    paths = {
        split: dataset_directory / f"{split}.jsonl"
        for split in ("train", "validation", "test")
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Dataset file not found: {path}")

    all_samples = {
        split: load_jsonl(path)
        for split, path in paths.items()
    }
    for samples in all_samples.values():
        validate_dataset_samples(samples, DRONE_COMMAND_SCHEMA)

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(paths["train"]),
            "validation": str(paths["validation"]),
        },
    )
    return (
        dataset["train"],
        dataset["validation"],
        all_samples["test"],
    )


def tokenize_dataset(
    dataset: Dataset,
    tokenizer: Any,
    max_sequence_length: int,
) -> Dataset:
    """System Prompt를 삽입하고 Assistant 정답에만 label을 생성한다."""

    def tokenize_sample(sample: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *sample["messages"],
        ]
        prompt_messages = messages[:-1]
        input_ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
        )
        prompt_ids = tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=True,
            add_generation_prompt=True,
        )

        if input_ids[: len(prompt_ids)] != prompt_ids:
            raise ValueError(
                "Chat Template prompt tokens do not match the full sample prefix"
            )

        input_ids = input_ids[:max_sequence_length]
        prompt_length = min(len(prompt_ids), len(input_ids))
        labels = [-100] * prompt_length + input_ids[prompt_length:]
        if not any(label != -100 for label in labels):
            raise ValueError(
                "Assistant answer was truncated. Increase max sequence length."
            )

        return {
            "input_ids": input_ids,
            "attention_mask": [1] * len(input_ids),
            "labels": labels,
        }

    return dataset.map(
        tokenize_sample,
        remove_columns=dataset.column_names,
        desc="Applying Qwen chat template",
    )


def load_base_model(model_name: str) -> tuple[Any, Any]:
    """A100 학습용 Qwen 원본 모델과 Tokenizer를 로드한다."""
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA GPU is required for this training script. "
            "Run it on the KT Cloud A100 server."
        )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
    )
    model.to("cuda")
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    return model, tokenizer


def build_training_arguments(
    arguments: argparse.Namespace,
    run_directory: Path,
) -> TrainingArguments:
    """LoRA 학습에 사용할 Transformers 설정을 생성한다."""
    return TrainingArguments(
        output_dir=str(run_directory / "checkpoints"),
        num_train_epochs=arguments.epochs,
        per_device_train_batch_size=arguments.batch_size,
        per_device_eval_batch_size=arguments.batch_size,
        gradient_accumulation_steps=(
            arguments.gradient_accumulation_steps
        ),
        learning_rate=arguments.learning_rate,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=1,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=2,
        bf16=True,
        fp16=False,
        gradient_checkpointing=True,
        optim="adamw_torch",
        report_to="none",
        seed=arguments.seed,
        data_seed=arguments.seed,
    )


def main() -> None:
    """기준 평가, LoRA 학습, 사후 평가와 보고서 생성을 실행한다."""
    arguments = parse_arguments()
    run_directory = build_run_directory(arguments.output_root)
    logger = configure_experiment_logger(
        run_directory / "training_log.txt"
    )
    logger.info("실험 디렉터리: %s", run_directory)

    set_random_seed(arguments.seed)
    environment_info = collect_environment_info(REPOSITORY_ROOT)
    log_mapping(logger, "실행 환경", environment_info)

    train_dataset, validation_dataset, test_samples = (
        load_and_validate_datasets(arguments.dataset_dir.resolve())
    )
    dataset_info = {
        "dataset_directory": str(arguments.dataset_dir.resolve()),
        "train_samples": len(train_dataset),
        "validation_samples": len(validation_dataset),
        "test_samples": len(test_samples),
    }
    log_mapping(logger, "Dataset", dataset_info)

    training_config = {
        "base_model": arguments.model_name,
        "epochs": arguments.epochs,
        "learning_rate": arguments.learning_rate,
        "batch_size": arguments.batch_size,
        "gradient_accumulation_steps": (
            arguments.gradient_accumulation_steps
        ),
        "max_sequence_length": arguments.max_sequence_length,
        "random_seed": arguments.seed,
        "lora_rank": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "lora_dropout": LORA_DROPOUT,
        "lora_target_modules": LORA_TARGET_MODULES,
    }
    log_mapping(logger, "학습 설정", training_config)
    write_json(
        run_directory / "experiment_config.json",
        {
            "environment": environment_info,
            "dataset": dataset_info,
            "training": training_config,
        },
    )

    logger.info("원본 Qwen 모델을 로드합니다.")
    model, tokenizer = load_base_model(arguments.model_name)

    baseline_records = []
    baseline_metrics = _empty_metrics(test_samples)
    if not arguments.skip_baseline_evaluation:
        logger.info("파인튜닝 전 기준 평가를 시작합니다.")
        baseline_records, baseline_metrics = evaluate_model(
            model=model,
            tokenizer=tokenizer,
            samples=test_samples,
            system_prompt=SYSTEM_PROMPT,
            schema=DRONE_COMMAND_SCHEMA,
            output_path=(
                run_directory / "baseline_predictions.jsonl"
            ),
            max_new_tokens=arguments.max_new_tokens,
        )
        log_mapping(logger, "파인튜닝 전 평가", baseline_metrics)

    tokenized_train = tokenize_dataset(
        train_dataset,
        tokenizer,
        arguments.max_sequence_length,
    )
    tokenized_validation = tokenize_dataset(
        validation_dataset,
        tokenizer,
        arguments.max_sequence_length,
    )

    lora_config = LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGET_MODULES,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )
    trainer = Trainer(
        model=model,
        args=build_training_arguments(arguments, run_directory),
        train_dataset=tokenized_train,
        eval_dataset=tokenized_validation,
        data_collator=data_collator,
        callbacks=[TrainerLogCallback(logger)],
    )

    logger.info("LoRA 학습을 시작합니다.")
    train_result = trainer.train()
    logger.info("LoRA 학습이 완료되었습니다.")
    trainer.log_metrics("train", train_result.metrics)
    trainer.save_metrics("train", train_result.metrics)

    adapter_directory = run_directory / "adapter"
    trainer.save_model(str(adapter_directory))
    tokenizer.save_pretrained(adapter_directory)
    logger.info("LoRA Adapter 저장: %s", adapter_directory)

    logger.info("파인튜닝 후 평가를 시작합니다.")
    fine_tuned_records, fine_tuned_metrics = evaluate_model(
        model=model,
        tokenizer=tokenizer,
        samples=test_samples,
        system_prompt=SYSTEM_PROMPT,
        schema=DRONE_COMMAND_SCHEMA,
        output_path=(
            run_directory / "finetuned_predictions.jsonl"
        ),
        max_new_tokens=arguments.max_new_tokens,
    )
    log_mapping(logger, "파인튜닝 후 평가", fine_tuned_metrics)

    failures = select_failures(fine_tuned_records)
    write_jsonl(run_directory / "failures.jsonl", failures)
    metrics = {
        "baseline": baseline_metrics,
        "fine_tuned": fine_tuned_metrics,
    }
    write_json(run_directory / "metrics.json", metrics)

    if baseline_records:
        report_info = {
            "실험 ID": run_directory.name,
            "Git Commit": environment_info["git_commit"],
            "Base Model": arguments.model_name,
            "Dataset": arguments.dataset_dir.name,
            "Train / Validation / Test": (
                f"{len(train_dataset)} / "
                f"{len(validation_dataset)} / "
                f"{len(test_samples)}"
            ),
            "GPU": environment_info["gpu"],
        }
        write_comparison_report(
            path=run_directory / "comparison_report.txt",
            experiment_info=report_info,
            baseline_records=baseline_records,
            baseline_metrics=baseline_metrics,
            fine_tuned_records=fine_tuned_records,
            fine_tuned_metrics=fine_tuned_metrics,
        )

    logger.info("남은 실패 샘플 수: %d", len(failures))
    logger.info("모든 결과 저장 완료: %s", run_directory)


def _empty_metrics(test_samples: list[dict[str, Any]]) -> dict[str, Any]:
    """기준 평가를 생략할 때 사용할 빈 지표를 생성한다."""
    return {
        "samples": len(test_samples),
        "json_parse": 0.0,
        "schema_valid": 0.0,
        "status_match": 0.0,
        "command_match": 0.0,
        "parameter_match": 0.0,
        "exact_match": 0.0,
        "hanja_free": 0.0,
        "categories": {},
    }


if __name__ == "__main__":
    main()
