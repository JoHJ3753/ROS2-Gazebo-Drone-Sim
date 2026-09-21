"""원본 모델과 파인튜닝 모델의 드론 명령 성능을 평가한다."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import torch
from jsonschema import Draft7Validator


HANJA_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
NUMBER_PATTERN = re.compile(r"\d")

VISION_KEYWORDS = (
    "물체",
    "사람",
    "차량",
    "자동차",
    "추적",
    "찾아",
    "보이면",
)
RELATIVE_POSITION_KEYWORDS = (
    "현재 위치",
    "이 자리",
    "지금 높이",
    "기수를 유지",
    "기수를 고정",
    "시 방향",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL 파일을 샘플 목록으로 읽는다."""
    samples = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue

        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSONL at {path}:{line_number}: {error}"
            ) from error

    return samples


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """평가 레코드를 UTF-8 JSONL 파일로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_dataset_samples(
    samples: list[dict[str, Any]],
    schema: dict[str, Any],
) -> None:
    """Dataset 메시지 구조와 정답 JSON Schema를 검증한다."""
    validator = Draft7Validator(schema)

    for index, sample in enumerate(samples, start=1):
        messages = sample.get("messages")
        if not isinstance(messages, list) or len(messages) != 2:
            raise ValueError(
                f"Sample {index} must contain one user and one assistant message"
            )

        roles = [message.get("role") for message in messages]
        if roles != ["user", "assistant"]:
            raise ValueError(
                f"Sample {index} has invalid message roles: {roles}"
            )

        try:
            expected = json.loads(messages[1]["content"])
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Sample {index} has invalid assistant JSON: {error}"
            ) from error

        errors = sorted(
            validator.iter_errors(expected),
            key=lambda item: list(item.path),
        )
        if errors:
            raise ValueError(
                f"Sample {index} violates the command schema: "
                f"{errors[0].message}"
            )


def classify_sample(user_text: str, expected: dict[str, Any]) -> str:
    """발표 자료용 테스트 유형을 결정한다."""
    if any(keyword in user_text for keyword in VISION_KEYWORDS):
        return "vision_language"

    if expected["status"] != "accepted":
        return "ambiguous_or_impossible"

    if len(expected["commands"]) > 1:
        return "compound"

    if any(
        keyword in user_text
        for keyword in RELATIVE_POSITION_KEYWORDS
    ):
        return "relative_position"

    if NUMBER_PATTERN.search(user_text):
        return "numeric"

    return "basic_single"


def compare_prediction(
    raw_prediction: str,
    expected: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, bool]:
    """모델 출력과 정답을 단계별로 비교한다."""
    metrics = {
        "json_parse": False,
        "schema_valid": False,
        "status_match": False,
        "command_match": False,
        "parameter_match": False,
        "exact_match": False,
        "hanja_free": not bool(HANJA_PATTERN.search(raw_prediction)),
    }

    try:
        prediction = json.loads(raw_prediction)
    except json.JSONDecodeError:
        return metrics

    metrics["json_parse"] = True

    validator = Draft7Validator(schema)
    metrics["schema_valid"] = validator.is_valid(prediction)
    if not isinstance(prediction, dict):
        return metrics

    metrics["status_match"] = (
        prediction.get("status") == expected.get("status")
    )

    predicted_commands = prediction.get("commands")
    expected_commands = expected.get("commands")
    if not isinstance(predicted_commands, list):
        return metrics

    predicted_names = [
        command.get("name")
        for command in predicted_commands
        if isinstance(command, dict)
    ]
    expected_names = [command["name"] for command in expected_commands]
    metrics["command_match"] = predicted_names == expected_names

    predicted_arguments = [
        command.get("arguments")
        for command in predicted_commands
        if isinstance(command, dict)
    ]
    expected_arguments = [
        command["arguments"]
        for command in expected_commands
    ]
    metrics["parameter_match"] = (
        len(predicted_arguments) == len(predicted_commands)
        and predicted_arguments == expected_arguments
    )
    metrics["exact_match"] = prediction == expected
    return metrics


def calculate_metrics(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """샘플별 평가 결과를 전체 및 유형별 정확도로 집계한다."""
    metric_names = (
        "json_parse",
        "schema_valid",
        "status_match",
        "command_match",
        "parameter_match",
        "exact_match",
        "hanja_free",
    )
    total = len(records)
    totals = Counter()
    category_totals: dict[str, Counter[str]] = {}

    for record in records:
        category = record["category"]
        category_counter = category_totals.setdefault(
            category,
            Counter(),
        )
        category_counter["samples"] += 1

        for metric_name in metric_names:
            if record["metrics"][metric_name]:
                totals[metric_name] += 1
                category_counter[metric_name] += 1

    percentages = {
        metric_name: _percentage(totals[metric_name], total)
        for metric_name in metric_names
    }
    category_metrics = {}
    for category, counter in category_totals.items():
        sample_count = counter["samples"]
        category_metrics[category] = {
            "samples": sample_count,
            **{
                metric_name: _percentage(
                    counter[metric_name],
                    sample_count,
                )
                for metric_name in metric_names
            },
        }

    return {
        "samples": total,
        **percentages,
        "categories": category_metrics,
    }


def _percentage(success_count: int, total_count: int) -> float:
    """성공 개수를 소수점 둘째 자리 백분율로 변환한다."""
    if total_count == 0:
        return 0.0
    return round(success_count / total_count * 100.0, 2)


@torch.inference_mode()
def evaluate_model(
    model: Any,
    tokenizer: Any,
    samples: list[dict[str, Any]],
    system_prompt: str,
    schema: dict[str, Any],
    output_path: Path,
    max_new_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """모델로 Test Dataset을 추론하고 상세 결과를 저장한다."""
    model.eval()
    records = []

    for sample_index, sample in enumerate(samples, start=1):
        user_message = sample["messages"][0]["content"]
        expected = json.loads(sample["messages"][1]["content"])
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
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
        generated = model.generate(
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
        prediction = tokenizer.decode(
            generated[0][prompt_length:],
            skip_special_tokens=True,
        ).strip()
        metrics = compare_prediction(prediction, expected, schema)
        records.append(
            {
                "sample_index": sample_index,
                "category": classify_sample(user_message, expected),
                "input": user_message,
                "expected": expected,
                "prediction_raw": prediction,
                "metrics": metrics,
            }
        )

    write_jsonl(output_path, records)
    return records, calculate_metrics(records)


def write_comparison_report(
    path: Path,
    experiment_info: dict[str, Any],
    baseline_records: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
    fine_tuned_records: list[dict[str, Any]],
    fine_tuned_metrics: dict[str, Any],
    robustness_baseline_records: list[dict[str, Any]] | None = None,
    robustness_baseline_metrics: dict[str, Any] | None = None,
    robustness_fine_tuned_records: list[dict[str, Any]] | None = None,
    robustness_fine_tuned_metrics: dict[str, Any] | None = None,
) -> None:
    """파인튜닝 전후 결과를 발표 자료용 TXT로 작성한다."""
    lines = [
        "=" * 72,
        "Qwen2.5 드론 명령 파인튜닝 전후 비교 보고서",
        "=" * 72,
        "",
    ]
    for key, value in experiment_info.items():
        lines.append(f"{key}: {value}")

    lines.extend(
        [
            "",
            "[전체 성능]",
            _metric_header(),
        ]
    )
    metric_labels = {
        "json_parse": "JSON 파싱 성공률",
        "schema_valid": "Schema 검증 통과율",
        "status_match": "Status 정확도",
        "command_match": "명령 이름·순서 정확도",
        "parameter_match": "파라미터 정확도",
        "exact_match": "전체 완전 일치 정확도",
        "hanja_free": "한자 미포함 비율",
    }
    for metric_name, label in metric_labels.items():
        lines.append(
            f"{label:<24}"
            f"{baseline_metrics[metric_name]:>12.2f}%"
            f"{fine_tuned_metrics[metric_name]:>14.2f}%"
        )

    lines.extend(["", "[유형별 완전 일치 정확도]"])
    categories = sorted(
        set(baseline_metrics["categories"])
        | set(fine_tuned_metrics["categories"])
    )
    for category in categories:
        baseline_category = baseline_metrics["categories"].get(
            category,
            {"samples": 0, "exact_match": 0.0},
        )
        fine_tuned_category = fine_tuned_metrics["categories"].get(
            category,
            {"samples": 0, "exact_match": 0.0},
        )
        lines.append(
            f"{category:<24}"
            f"샘플 {baseline_category['samples']:>3}개 | "
            f"전 {baseline_category['exact_match']:>6.2f}% | "
            f"후 {fine_tuned_category['exact_match']:>6.2f}%"
        )

    improved_records = []
    remaining_failures = []
    for baseline, fine_tuned in zip(
        baseline_records,
        fine_tuned_records,
        strict=True,
    ):
        baseline_passed = baseline["metrics"]["exact_match"]
        fine_tuned_passed = fine_tuned["metrics"]["exact_match"]
        if not baseline_passed and fine_tuned_passed:
            improved_records.append((baseline, fine_tuned))
        if not fine_tuned_passed:
            remaining_failures.append((baseline, fine_tuned))

    _append_examples(lines, "대표 개선 사례", improved_records)
    _append_examples(lines, "학습 후 남은 실패 사례", remaining_failures)

    if (
        robustness_baseline_records is not None
        and robustness_baseline_metrics is not None
        and robustness_fine_tuned_records is not None
        and robustness_fine_tuned_metrics is not None
        and robustness_fine_tuned_records
    ):
        _append_robustness_report(
            lines=lines,
            baseline_records=robustness_baseline_records,
            baseline_metrics=robustness_baseline_metrics,
            fine_tuned_records=robustness_fine_tuned_records,
            fine_tuned_metrics=robustness_fine_tuned_metrics,
            metric_labels=metric_labels,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_robustness_report(
    lines: list[str],
    baseline_records: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
    fine_tuned_records: list[dict[str, Any]],
    fine_tuned_metrics: dict[str, Any],
    metric_labels: dict[str, str],
) -> None:
    """비교 보고서에 오타·사투리 강건성 평가 결과를 추가한다."""
    lines.extend(
        [
            "",
            "[오타·사투리 강건성 성능]",
            _metric_header(),
        ]
    )
    for metric_name, label in metric_labels.items():
        lines.append(
            f"{label:<24}"
            f"{baseline_metrics[metric_name]:>12.2f}%"
            f"{fine_tuned_metrics[metric_name]:>14.2f}%"
        )

    improved_records = []
    remaining_failures = []
    for baseline, fine_tuned in zip(
        baseline_records,
        fine_tuned_records,
        strict=True,
    ):
        baseline_passed = baseline["metrics"]["exact_match"]
        fine_tuned_passed = fine_tuned["metrics"]["exact_match"]
        if not baseline_passed and fine_tuned_passed:
            improved_records.append((baseline, fine_tuned))
        if not fine_tuned_passed:
            remaining_failures.append((baseline, fine_tuned))

    _append_examples(
        lines,
        "오타·사투리 대표 개선 사례",
        improved_records,
    )
    _append_examples(
        lines,
        "오타·사투리 학습 후 남은 실패 사례",
        remaining_failures,
    )


def _metric_header() -> str:
    """성능 비교 표의 머리글을 반환한다."""
    return f"{'평가 항목':<24}{'파인튜닝 전':>13}{'파인튜닝 후':>15}"


def _append_examples(
    lines: list[str],
    title: str,
    records: list[tuple[dict[str, Any], dict[str, Any]]],
    maximum_examples: int = 10,
) -> None:
    """비교 보고서에 대표 샘플을 추가한다."""
    lines.extend(["", f"[{title}]"])
    if not records:
        lines.append("해당 사례 없음")
        return

    for index, (baseline, fine_tuned) in enumerate(
        records[:maximum_examples],
        start=1,
    ):
        lines.extend(
            [
                "",
                f"사례 {index}",
                f"분류: {fine_tuned['category']}",
                f"입력: {fine_tuned['input']}",
                "예상:",
                json.dumps(
                    fine_tuned["expected"],
                    ensure_ascii=False,
                ),
                "파인튜닝 전:",
                baseline["prediction_raw"],
                "파인튜닝 후:",
                fine_tuned["prediction_raw"],
            ]
        )


def select_failures(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """전체 완전 일치에 실패한 평가 레코드만 반환한다."""
    return [
        record
        for record in records
        if not record["metrics"]["exact_match"]
    ]
