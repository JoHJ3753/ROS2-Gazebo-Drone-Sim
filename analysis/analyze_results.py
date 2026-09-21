"""파인튜닝 결과를 CSV, 그래프, 요약 보고서로 변환한다."""

import argparse
import csv
import hashlib
import json
import os
import re
import warnings
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "test_result"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "analysis" / "outputs"

METRIC_NAMES = (
    "json_parse",
    "schema_valid",
    "status_match",
    "command_match",
    "parameter_match",
    "exact_match",
    "hanja_free",
)
CORE_METRICS = (
    "json_parse",
    "command_match",
    "parameter_match",
    "exact_match",
)
PRESENTATION_COLORS = {
    "baseline": "#9CA3AF",
    "fine_tuned": "#2563EB",
    "json_parse": "#2563EB",
    "command_match": "#059669",
    "parameter_match": "#D97706",
    "exact_match": "#7C3AED",
}
LOSS_MOVING_AVERAGE_WINDOW = 5
FAILURE_ORDER = (
    "json_parse_failure",
    "schema_failure",
    "status_mismatch",
    "command_mismatch",
    "parameter_mismatch",
    "exact_response_mismatch",
    "success",
)
FAILURE_LABELS = {
    "json_parse_failure": "JSON 파싱 실패",
    "schema_failure": "Schema 실패",
    "status_mismatch": "상태 불일치",
    "command_mismatch": "명령 불일치",
    "parameter_mismatch": "파라미터 불일치",
    "exact_response_mismatch": "응답 메시지 불일치",
    "success": "완전 일치",
}
METRIC_LABELS = {
    "json_parse": "JSON 파싱",
    "schema_valid": "Schema 통과",
    "status_match": "상태",
    "command_match": "명령",
    "parameter_match": "파라미터",
    "exact_match": "완전 일치",
    "hanja_free": "한자 미포함",
}

TRAINER_LOG_PATTERN = re.compile(
    r"trainer_step=(?P<step>\d+)\s*\|\s*(?P<values>.+)$"
)
KEY_VALUE_PATTERN = re.compile(
    r"(?P<key>[A-Za-z_]+)=(?P<value>[^|]+?)(?=\s*\||$)"
)
LOG_SETTING_PATTERN = re.compile(
    r"\| INFO \| (?P<key>[A-Za-z_]+): (?P<value>.+)$"
)
VERSION_PATTERN = re.compile(
    r"^test_result_(?P<label>v(?P<major>\d+)\.(?P<minor>\d+)(?P<suffix>.*))$"
)


def parse_arguments() -> argparse.Namespace:
    """명령행 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Qwen 드론 명령 파인튜닝 결과 분석",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    return parser.parse_args()


def version_sort_key(path: Path) -> tuple[int, int, str]:
    """결과 폴더를 버전 번호와 접미사 순서로 정렬한다."""
    match = VERSION_PATTERN.match(path.name)
    if match is None:
        return (10**9, 10**9, path.name)
    return (
        int(match.group("major")),
        int(match.group("minor")),
        match.group("suffix"),
    )


def discover_result_directories(results_root: Path) -> list[Path]:
    """필수 평가 파일을 가진 결과 폴더를 자동으로 찾는다."""
    directories = []
    for path in results_root.glob("test_result_v*"):
        if not path.is_dir():
            continue
        required_files = (
            path / "metrics.json",
            path / "baseline_predictions.jsonl",
            path / "finetuned_predictions.jsonl",
        )
        if all(file_path.is_file() for file_path in required_files):
            directories.append(path)
    return sorted(directories, key=version_sort_key)


def version_label(result_directory: Path) -> str:
    """결과 폴더 이름에서 표시용 버전을 반환한다."""
    return result_directory.name.removeprefix("test_result_")


def load_json(path: Path) -> dict[str, Any]:
    """UTF-8 JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """UTF-8 JSONL 파일을 읽는다."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def benchmark_fingerprint(records: list[dict[str, Any]]) -> str:
    """입력과 정답으로 시험셋 식별용 해시를 생성한다."""
    benchmark = [
        {
            "input": record["input"],
            "expected": record["expected"],
        }
        for record in records
    ]
    canonical = json.dumps(
        benchmark,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[dict[str, Any]],
) -> None:
    """Excel 호환 UTF-8 BOM CSV를 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def collect_version_metrics(
    result_directories: list[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """전체 지표와 파인튜닝 전후 개선 폭을 수집한다."""
    metric_rows = []
    improvement_rows = []
    for result_directory in result_directories:
        version = version_label(result_directory)
        metrics = load_json(result_directory / "metrics.json")
        records = load_jsonl(
            result_directory / "finetuned_predictions.jsonl"
        )
        fingerprint = benchmark_fingerprint(records)
        for phase in ("baseline", "fine_tuned"):
            phase_metrics = metrics[phase]
            row = {
                "version": version,
                "benchmark_id": fingerprint,
                "phase": phase,
                "samples": phase_metrics["samples"],
            }
            row.update(
                {
                    metric_name: phase_metrics[metric_name]
                    for metric_name in METRIC_NAMES
                }
            )
            metric_rows.append(row)

        for metric_name in METRIC_NAMES:
            baseline = metrics["baseline"][metric_name]
            fine_tuned = metrics["fine_tuned"][metric_name]
            improvement_rows.append(
                {
                    "version": version,
                    "benchmark_id": fingerprint,
                    "metric": metric_name,
                    "baseline": baseline,
                    "fine_tuned": fine_tuned,
                    "improvement_percentage_points": round(
                        fine_tuned - baseline,
                        2,
                    ),
                }
            )
    return metric_rows, improvement_rows


def collect_category_metrics(
    result_directories: list[Path],
) -> list[dict[str, Any]]:
    """버전·단계·테스트 유형별 지표를 평탄화한다."""
    rows = []
    for result_directory in result_directories:
        version = version_label(result_directory)
        metrics = load_json(result_directory / "metrics.json")
        records = load_jsonl(
            result_directory / "finetuned_predictions.jsonl"
        )
        fingerprint = benchmark_fingerprint(records)
        for phase in ("baseline", "fine_tuned"):
            categories = metrics[phase].get("categories", {})
            for category, values in sorted(categories.items()):
                row = {
                    "version": version,
                    "benchmark_id": fingerprint,
                    "phase": phase,
                    "category": category,
                    "samples": values["samples"],
                }
                row.update(
                    {
                        metric_name: values[metric_name]
                        for metric_name in METRIC_NAMES
                    }
                )
                rows.append(row)
    return rows


def percent(success_count: int, sample_count: int) -> float:
    """성공 건수를 백분율로 변환한다."""
    if sample_count == 0:
        return 0.0
    return round(success_count / sample_count * 100.0, 2)


def expected_command_names(record: dict[str, Any]) -> list[str]:
    """평가 레코드의 기대 명령 이름을 순서대로 반환한다."""
    return [
        command["name"]
        for command in record["expected"].get("commands", [])
    ]


def prediction_path(result_directory: Path, phase: str) -> Path:
    """평가 단계에 대응하는 기존 예측 파일 경로를 반환한다."""
    file_names = {
        "baseline": "baseline_predictions.jsonl",
        "fine_tuned": "finetuned_predictions.jsonl",
    }
    return result_directory / file_names[phase]


def collect_command_metrics(
    result_directories: list[Path],
) -> list[dict[str, Any]]:
    """기대 명령이 있는 샘플의 명령별 성공률을 계산한다."""
    rows = []
    for result_directory in result_directories:
        version = version_label(result_directory)
        fine_tuned_records = load_jsonl(
            result_directory / "finetuned_predictions.jsonl"
        )
        fingerprint = benchmark_fingerprint(fine_tuned_records)
        for phase in ("baseline", "fine_tuned"):
            records = load_jsonl(
                prediction_path(result_directory, phase)
            )
            counters: dict[str, Counter[str]] = defaultdict(Counter)
            for record in records:
                command_names = set(expected_command_names(record))
                for command_name in command_names:
                    counter = counters[command_name]
                    counter["samples"] += 1
                    for metric_name in (
                        "command_match",
                        "parameter_match",
                        "exact_match",
                    ):
                        if record["metrics"][metric_name]:
                            counter[metric_name] += 1
            for command_name, counter in sorted(counters.items()):
                samples = counter["samples"]
                rows.append(
                    {
                        "version": version,
                        "benchmark_id": fingerprint,
                        "phase": phase,
                        "command": command_name,
                        "samples": samples,
                        "command_match": percent(
                            counter["command_match"],
                            samples,
                        ),
                        "parameter_match": percent(
                            counter["parameter_match"],
                            samples,
                        ),
                        "exact_match": percent(
                            counter["exact_match"],
                            samples,
                        ),
                    }
                )
    return rows


def classify_failure(metrics: dict[str, bool]) -> str:
    """평가 실패를 최초 실패 단계 하나로 분류한다."""
    checks = (
        ("json_parse", "json_parse_failure"),
        ("schema_valid", "schema_failure"),
        ("status_match", "status_mismatch"),
        ("command_match", "command_mismatch"),
        ("parameter_match", "parameter_mismatch"),
        ("exact_match", "exact_response_mismatch"),
    )
    for metric_name, failure_type in checks:
        if not metrics[metric_name]:
            return failure_type
    return "success"


def collect_failure_analysis(
    result_directories: list[Path],
) -> list[dict[str, Any]]:
    """모든 평가 샘플을 계층적 실패 유형으로 분류한다."""
    rows = []
    for result_directory in result_directories:
        version = version_label(result_directory)
        fine_tuned_records = load_jsonl(
            result_directory / "finetuned_predictions.jsonl"
        )
        fingerprint = benchmark_fingerprint(fine_tuned_records)
        for phase in ("baseline", "fine_tuned"):
            records = load_jsonl(
                prediction_path(result_directory, phase)
            )
            for record in records:
                metrics = record["metrics"]
                rows.append(
                    {
                        "version": version,
                        "benchmark_id": fingerprint,
                        "phase": phase,
                        "sample_index": record["sample_index"],
                        "category": record["category"],
                        "input": record["input"],
                        "expected_status": record["expected"]["status"],
                        "expected_commands": ",".join(
                            expected_command_names(record)
                        ),
                        "failure_type": classify_failure(metrics),
                        "prediction_raw": record["prediction_raw"],
                    }
                )
    return rows


def find_training_log(result_directory: Path) -> Path | None:
    """확장자 유무를 모두 고려해 학습 로그를 찾는다."""
    for file_name in ("training_log.txt", "training_log"):
        path = result_directory / file_name
        if path.is_file():
            return path
    return None


def parse_numeric(value: str) -> float | None:
    """로그 문자열을 유한 실수로 변환한다."""
    try:
        return float(value.strip())
    except ValueError:
        return None


def collect_training_curves(
    result_directories: list[Path],
) -> list[dict[str, Any]]:
    """Transformers Trainer 로그에서 학습 곡선 값을 추출한다."""
    rows = []
    for result_directory in result_directories:
        log_path = find_training_log(result_directory)
        if log_path is None:
            continue
        version = version_label(result_directory)
        for line in log_path.read_text(encoding="utf-8").splitlines():
            match = TRAINER_LOG_PATTERN.search(line)
            if match is None:
                continue
            values = {
                key_value.group("key"): parse_numeric(
                    key_value.group("value")
                )
                for key_value in KEY_VALUE_PATTERN.finditer(
                    match.group("values")
                )
            }
            if values.get("eval_loss") is not None:
                event_type = "validation"
            elif values.get("train_loss") is not None:
                event_type = "summary"
            elif values.get("loss") is not None:
                event_type = "train_step"
            else:
                continue
            rows.append(
                {
                    "version": version,
                    "event_type": event_type,
                    "step": int(match.group("step")),
                    "epoch": values.get("epoch"),
                    "loss": values.get("loss"),
                    "eval_loss": values.get("eval_loss"),
                    "train_loss": values.get("train_loss"),
                    "learning_rate": values.get("learning_rate"),
                    "grad_norm": values.get("grad_norm"),
                }
            )
    return rows


def collect_experiment_metadata(
    result_directories: list[Path],
    training_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """학습 로그에서 데이터셋과 하이퍼파라미터를 정리한다."""
    final_values: dict[str, dict[str, float]] = defaultdict(dict)
    for row in training_rows:
        if row["event_type"] == "summary":
            final_values[row["version"]]["train_loss"] = row["train_loss"]
        if row["event_type"] == "validation":
            final_values[row["version"]]["final_eval_loss"] = row["eval_loss"]

    rows = []
    selected_keys = {
        "git_commit",
        "gpu",
        "dataset_directory",
        "train_samples",
        "validation_samples",
        "test_samples",
        "base_model",
        "initial_adapter",
        "epochs",
        "learning_rate",
        "batch_size",
        "gradient_accumulation_steps",
        "max_sequence_length",
        "random_seed",
        "lora_rank",
        "lora_alpha",
        "lora_dropout",
    }
    for result_directory in result_directories:
        log_path = find_training_log(result_directory)
        if log_path is None:
            continue
        settings: dict[str, str] = {}
        for line in log_path.read_text(encoding="utf-8").splitlines():
            match = LOG_SETTING_PATTERN.search(line)
            if match is not None and match.group("key") in selected_keys:
                settings.setdefault(match.group("key"), match.group("value"))
        version = version_label(result_directory)
        initial_adapter = settings.get("initial_adapter", "")
        rows.append(
            {
                "version": version,
                "training_source": (
                    "continued_adapter" if initial_adapter else "base_model"
                ),
                "dataset": Path(
                    settings.get("dataset_directory", "unknown")
                ).name,
                **settings,
                **final_values.get(version, {}),
            }
        )
    return rows


def configure_matplotlib() -> Any:
    """한글 발표용 그래프 설정 후 pyplot을 반환한다."""
    os.environ.setdefault(
        "MPLCONFIGDIR",
        "/tmp/codex_matplotlib_cache",
    )
    warnings.filterwarnings(
        "ignore",
        message="Unable to import Axes3D.*",
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_path = Path(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    )
    font_family = "DejaVu Sans"
    if font_path.is_file():
        font_manager.fontManager.addfont(str(font_path))
        font_family = font_manager.FontProperties(
            fname=str(font_path)
        ).get_name()

    plt.rcParams.update(
        {
            "font.family": font_family,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#9CA3AF",
            "axes.labelcolor": "#1F2937",
            "xtick.color": "#374151",
            "ytick.color": "#374151",
            "text.color": "#111827",
        }
    )
    return plt


def save_figure(plt: Any, path: Path) -> None:
    """현재 Figure를 발표용 PNG로 저장하고 닫는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close()


def sorted_versions(versions: Iterable[str]) -> list[str]:
    """버전 문자열을 숫자 버전 순서로 정렬한다."""
    return sorted(
        versions,
        key=lambda item: version_sort_key(Path(f"test_result_{item}")),
    )


def draw_accuracy_bars(
    axis: Any,
    rows: list[dict[str, Any]],
    title: str,
) -> None:
    """한 시험셋 그룹의 정확도 막대를 그린다."""
    rows = sorted(
        rows,
        key=lambda row: version_sort_key(
            Path(f"test_result_{row['version']}")
        ),
    )
    positions = list(range(len(rows)))
    width = 0.19
    for index, metric_name in enumerate(CORE_METRICS):
        offsets = [
            position + (index - 1.5) * width
            for position in positions
        ]
        bars = axis.bar(
            offsets,
            [row[metric_name] for row in rows],
            width,
            label=METRIC_LABELS[metric_name],
            color=PRESENTATION_COLORS[metric_name],
        )
        axis.bar_label(bars, fmt="%.0f", padding=2, fontsize=8)
    axis.set_title(title, pad=14)
    axis.set_xticks(positions, [row["version"] for row in rows])
    axis.set_ylim(0, 110)
    axis.grid(axis="y", alpha=0.18)


def chart_overall_accuracy(
    plt: Any,
    metric_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """파인튜닝 후 핵심 정확도를 버전별 막대그래프로 그린다."""
    rows = [row for row in metric_rows if row["phase"] == "fine_tuned"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["benchmark_id"]].append(row)
    ordered_groups = sorted(
        groups.values(),
        key=lambda group: (-len(group), group[0]["version"]),
    )
    figure, axes = plt.subplots(
        1,
        len(ordered_groups),
        figsize=(13.5, 6.2),
        sharey=True,
        gridspec_kw={
            "width_ratios": [max(1.4, len(group)) for group in ordered_groups]
        },
    )
    if len(ordered_groups) == 1:
        axes = [axes]
    for index, (axis, group) in enumerate(zip(axes, ordered_groups)):
        title = "동일 시험셋 비교" if index == 0 else "별도 시험셋"
        draw_accuracy_bars(axis, group, title)
    axes[0].set_ylabel("정확도 (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.suptitle("버전별 파인튜닝 후 정확도", fontsize=16, y=1.02)
    figure.legend(
        handles,
        labels,
        ncols=4,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.98),
    )
    save_figure(plt, path)


def chart_improvements(
    plt: Any,
    improvement_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """명령·파라미터·완전 일치의 개선 폭을 비교한다."""
    selected_metrics = (
        "command_match",
        "parameter_match",
        "exact_match",
    )
    versions = sorted_versions({row["version"] for row in improvement_rows})
    lookup = {
        (row["version"], row["metric"]): row
        for row in improvement_rows
    }
    figure, axes = plt.subplots(1, 3, figsize=(14.5, 6.2), sharey=True)
    positions = list(range(len(versions)))
    for axis, metric_name in zip(axes, selected_metrics):
        baseline = [lookup[(version, metric_name)]["baseline"] for version in versions]
        fine_tuned = [
            lookup[(version, metric_name)]["fine_tuned"] for version in versions
        ]
        for position, start, end in zip(positions, baseline, fine_tuned):
            axis.plot([start, end], [position, position], color="#CBD5E1")
        axis.scatter(
            baseline,
            positions,
            color=PRESENTATION_COLORS["baseline"],
            s=55,
            label="파인튜닝 전",
            zorder=3,
        )
        axis.scatter(
            fine_tuned,
            positions,
            color=PRESENTATION_COLORS[metric_name],
            s=65,
            label="파인튜닝 후",
            zorder=3,
        )
        for position, start, end in zip(positions, baseline, fine_tuned):
            axis.text(start - 2, position, f"{start:.0f}", ha="right", va="center")
            axis.text(end + 2, position, f"{end:.0f}", ha="left", va="center")
        axis.set_title(METRIC_LABELS[metric_name])
        axis.set_xlim(-8, 108)
        axis.set_xlabel("정확도 (%)")
        axis.grid(axis="x", alpha=0.18)
    axes[0].set_yticks(positions, versions)
    axes[0].invert_yaxis()
    figure.suptitle("파인튜닝 전후 정확도 변화", fontsize=16, y=1.02)
    axes[-1].legend(loc="lower right")
    save_figure(plt, path)


def chart_command_accuracy(
    plt: Any,
    command_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """파인튜닝 후 명령별 명령 적중률을 히트맵으로 그린다."""
    rows = [row for row in command_rows if row["phase"] == "fine_tuned"]
    versions = sorted_versions({row["version"] for row in rows})
    commands = sorted({row["command"] for row in rows})
    lookup = {
        (row["command"], row["version"]): row
        for row in rows
    }
    matrix = [
        [
            lookup.get((command, version), {}).get(
                "command_match",
                float("nan"),
            )
            for version in versions
        ]
        for command in commands
    ]
    figure, axis = plt.subplots(
        figsize=(max(8.5, len(versions) * 1.4), max(6.0, len(commands) * 0.5))
    )
    color_map = plt.colormaps["YlGnBu"].copy()
    color_map.set_bad("#E5E7EB")
    image = axis.imshow(
        matrix,
        cmap=color_map,
        vmin=0,
        vmax=100,
        aspect="auto",
    )
    axis.set_title("명령별 파인튜닝 후 명령 적중률")
    axis.set_xticks(range(len(versions)), versions)
    axis.set_yticks(range(len(commands)), commands)
    for row_index, command in enumerate(commands):
        for column_index, version in enumerate(versions):
            row = lookup.get((command, version))
            value = None if row is None else row["command_match"]
            label = "표본 없음" if row is None else (
                f"{value:.0f}%\n(n={row['samples']})"
            )
            color = "white" if value is not None and value >= 65 else "#111827"
            axis.text(
                column_index,
                row_index,
                label,
                ha="center",
                va="center",
                color=color,
                fontsize=9,
            )
    colorbar = figure.colorbar(image, ax=axis, fraction=0.025, pad=0.02)
    colorbar.set_label("정확도 (%)")
    save_figure(plt, path)


def chart_failure_distribution(
    plt: Any,
    failure_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """파인튜닝 후 실패 원인과 성공 건수를 누적 막대로 그린다."""
    rows = [row for row in failure_rows if row["phase"] == "fine_tuned"]
    versions = sorted_versions({row["version"] for row in rows})
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts[row["version"]][row["failure_type"]] += 1
    colors = {
        "json_parse_failure": "#991B1B",
        "schema_failure": "#DC2626",
        "status_mismatch": "#F97316",
        "command_mismatch": "#F59E0B",
        "parameter_mismatch": "#EAB308",
        "exact_response_mismatch": "#A78BFA",
        "success": "#10B981",
    }
    figure, axis = plt.subplots(figsize=(10.5, 6.2))
    del figure
    totals = [sum(counts[version].values()) for version in versions]
    bottoms = [0.0] * len(versions)
    for failure_type in FAILURE_ORDER:
        values = [
            counts[version][failure_type] / total * 100
            for version, total in zip(versions, totals)
        ]
        bars = axis.bar(
            versions,
            values,
            bottom=bottoms,
            label=FAILURE_LABELS[failure_type],
            color=colors[failure_type],
        )
        labels = [f"{value:.0f}%" if value >= 8 else "" for value in values]
        axis.bar_label(
            bars,
            labels=labels,
            label_type="center",
            fontsize=8,
            color="white",
        )
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    axis.set_title("파인튜닝 후 성공 및 실패 원인 비율")
    axis.set_ylabel("비율 (%)")
    axis.set_ylim(0, 100)
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
    save_figure(plt, path)


def chart_training_loss(
    plt: Any,
    training_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """버전별 Step 학습 Loss를 선그래프로 그린다."""
    rows = [row for row in training_rows if row["event_type"] == "train_step"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["version"]].append(row)
    figure, axis = plt.subplots(figsize=(11, 6.2))
    del figure
    for version in sorted(
        grouped,
        key=lambda item: version_sort_key(Path(f"test_result_{item}")),
    ):
        values = sorted(grouped[version], key=lambda row: row["step"])
        steps = [row["step"] for row in values]
        losses = [row["loss"] for row in values]
        moving_average = [
            sum(losses[max(0, index - LOSS_MOVING_AVERAGE_WINDOW + 1):index + 1])
            / min(index + 1, LOSS_MOVING_AVERAGE_WINDOW)
            for index in range(len(losses))
        ]
        line = axis.plot(steps, moving_average, label=version, linewidth=2.2)[0]
        axis.plot(steps, losses, color=line.get_color(), alpha=0.18, linewidth=1.0)
    axis.set_title("버전별 학습 Loss")
    axis.set_xlabel("Trainer Step")
    axis.set_ylabel("Loss")
    axis.grid(alpha=0.2)
    axis.legend(ncols=3)
    save_figure(plt, path)


def chart_final_eval_loss(
    plt: Any,
    metadata_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """버전별 최종 Validation Loss를 막대그래프로 그린다."""
    rows = sorted(
        metadata_rows,
        key=lambda row: version_sort_key(Path(f"test_result_{row['version']}")),
    )
    figure, axis = plt.subplots(figsize=(9.5, 5.8))
    bars = axis.bar(
        [row["version"] for row in rows],
        [float(row["final_eval_loss"]) for row in rows],
        color=PRESENTATION_COLORS["fine_tuned"],
        width=0.62,
    )
    axis.bar_label(bars, fmt="%.4f", padding=4, fontsize=9)
    axis.set_title("버전별 최종 Validation Loss")
    axis.set_ylabel("Final Eval Loss")
    axis.grid(axis="y", alpha=0.18)
    save_figure(plt, path)


def chart_eval_loss_by_epoch(
    plt: Any,
    training_rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """2개 이상의 평가점이 있는 버전의 Epoch별 Loss를 그린다."""
    rows = [row for row in training_rows if row["event_type"] == "validation"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["version"]].append(row)
    grouped = {
        version: values
        for version, values in grouped.items()
        if len(values) > 1
    }
    if not grouped:
        return
    figure, axis = plt.subplots(figsize=(9.5, 5.8))
    del figure
    for version in sorted(
        grouped,
        key=lambda item: version_sort_key(Path(f"test_result_{item}")),
    ):
        values = sorted(grouped[version], key=lambda row: row["epoch"])
        axis.plot(
            [row["epoch"] for row in values],
            [row["eval_loss"] for row in values],
            marker="o",
            label=version,
            linewidth=1.8,
        )
    axis.set_title("다중 Epoch 버전의 Validation Loss 변화")
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Eval Loss")
    axis.grid(alpha=0.2)
    axis.legend(ncols=3)
    save_figure(plt, path)


def build_version_summary(
    metric_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """버전별 핵심 학습·평가 정보를 한 행으로 결합한다."""
    fine_tuned = {
        row["version"]: row
        for row in metric_rows
        if row["phase"] == "fine_tuned"
    }
    benchmark_labels: dict[str, str] = {}
    rows = []
    for metadata in sorted(
        metadata_rows,
        key=lambda row: version_sort_key(
            Path(f"test_result_{row['version']}")
        ),
    ):
        version = metadata["version"]
        metrics = fine_tuned.get(version)
        if metrics is None:
            continue
        benchmark_id = metrics["benchmark_id"]
        if benchmark_id not in benchmark_labels:
            group_index = len(benchmark_labels)
            benchmark_labels[benchmark_id] = (
                f"test_group_{chr(ord('A') + group_index)}"
            )
        rows.append(
            {
                "version": version,
                "benchmark_id": benchmark_id,
                "comparison_group": benchmark_labels[benchmark_id],
                "training_source": metadata.get("training_source", ""),
                "dataset": metadata.get("dataset", ""),
                "train_samples": metadata.get("train_samples", ""),
                "epochs": metadata.get("epochs", ""),
                "learning_rate": metadata.get("learning_rate", ""),
                "command_accuracy": metrics["command_match"],
                "parameter_accuracy": metrics["parameter_match"],
                "exact_accuracy": metrics["exact_match"],
                "train_loss": metadata.get("train_loss", ""),
                "eval_loss": metadata.get("final_eval_loss", ""),
            }
        )
    return rows


def write_summary(
    path: Path,
    metric_rows: list[dict[str, Any]],
    improvement_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
    command_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> None:
    """발표 자료 작성에 사용할 핵심 분석 내용을 TXT로 저장한다."""
    fine_tuned = [
        row for row in metric_rows if row["phase"] == "fine_tuned"
    ]
    benchmark_groups: dict[str, list[str]] = defaultdict(list)
    for row in fine_tuned:
        benchmark_groups[row["benchmark_id"]].append(row["version"])

    comparable_groups = [
        rows for rows in benchmark_groups.values() if len(rows) > 1
    ]
    lines = [
        "Qwen 드론 명령 파인튜닝 결과 분석",
        "=" * 48,
        "",
        "[비교 조건]",
    ]
    for benchmark_id, versions in benchmark_groups.items():
        lines.append(
            f"- 시험셋 {benchmark_id}: {', '.join(versions)}"
        )
    lines.append(
        "- 시험셋 식별자가 다른 버전의 절대 정확도는 "
        "직접 순위 비교하지 않는다."
    )
    continued_versions = [
        row["version"]
        for row in metadata_rows
        if row["training_source"] == "continued_adapter"
    ]
    if continued_versions:
        lines.append(
            "- 이어 학습 버전의 baseline은 원본 모델이 아니라 "
            "초기 어댑터 "
            f"성능이다: {', '.join(continued_versions)}"
        )

    lines.extend(["", "[파인튜닝 후 전체 지표]"])
    for row in fine_tuned:
        lines.append(
            f"- {row['version']}: "
            f"JSON {row['json_parse']:.2f}%, "
            f"명령 {row['command_match']:.2f}%, "
            f"파라미터 {row['parameter_match']:.2f}%, "
            f"완전 일치 {row['exact_match']:.2f}%"
        )

    if comparable_groups:
        lines.extend(["", "[동일 시험셋 내 최고 결과]"])
        metric_lookup = {
            row["version"]: row
            for row in fine_tuned
        }
        for versions in comparable_groups:
            best_version = max(
                versions,
                key=lambda version: metric_lookup[version]["exact_match"],
            )
            best = metric_lookup[best_version]
            lines.append(
                f"- {', '.join(versions)} 중 {best_version}의 완전 일치 "
                f"정확도가 {best['exact_match']:.2f}%로 가장 높다."
            )

    lines.extend(["", "[파인튜닝 개선 폭]"])
    exact_improvements = [
        row for row in improvement_rows if row["metric"] == "exact_match"
    ]
    for row in exact_improvements:
        lines.append(
            f"- {row['version']}: 완전 일치 "
            f"{row['baseline']:.2f}% → {row['fine_tuned']:.2f}% "
            f"({row['improvement_percentage_points']:+.2f}%p)"
        )

    lines.extend(["", "[파인튜닝 후 실패 요약]"])
    fine_failures = [
        row for row in failure_rows if row["phase"] == "fine_tuned"
    ]
    failure_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in fine_failures:
        failure_counts[row["version"]][row["failure_type"]] += 1
    for version in sorted(
        failure_counts,
        key=lambda item: version_sort_key(Path(f"test_result_{item}")),
    ):
        counts = failure_counts[version]
        failures = [
            f"{FAILURE_LABELS[failure_type]} {counts[failure_type]}건"
            for failure_type in FAILURE_ORDER
            if failure_type != "success" and counts[failure_type]
        ]
        lines.append(
            f"- {version}: " + (", ".join(failures) if failures else "실패 없음")
        )

    lines.extend(["", "[명령별 취약 항목]"])
    fine_command_rows = [
        row for row in command_rows if row["phase"] == "fine_tuned"
    ]
    for version in sorted(
        {row["version"] for row in fine_command_rows},
        key=lambda item: version_sort_key(Path(f"test_result_{item}")),
    ):
        version_rows = [
            row for row in fine_command_rows if row["version"] == version
        ]
        weak_rows = sorted(
            (
                row
                for row in version_rows
                if row["command_match"] < 100.0
            ),
            key=lambda row: (row["command_match"], row["command"]),
        )[:3]
        if not weak_rows:
            lines.append(
                f"- {version}: 평가된 명령 이름을 모두 적중했다."
            )
            continue
        descriptions = [
            f"{row['command']} {row['command_match']:.2f}% "
            f"(n={row['samples']})"
            for row in weak_rows
        ]
        lines.append(f"- {version}: {', '.join(descriptions)}")

    lines.extend(["", "[학습 설정과 Loss]"])
    for row in metadata_rows:
        source_label = (
            "이어 학습" if row["training_source"] == "continued_adapter"
            else "원본 모델"
        )
        lines.append(
            f"- {row['version']}: {source_label}, "
            f"Train {row.get('train_samples', '-')}건, "
            f"epoch {row.get('epochs', '-')}, "
            f"train_loss {float(row.get('train_loss', 0.0)):.4f}, "
            f"eval_loss {float(row.get('final_eval_loss', 0.0)):.4f}"
        )

    lines.extend(
        [
            "",
            "[해석 주의사항]",
            "- 전체 parameter_match에는 실행 명령이 비어 있는 "
            "거부 응답도 포함된다.",
            "- 명령별 CSV는 기대 명령이 있는 accepted 샘플만 "
            "별도로 집계한다.",
            "- 복합 명령 샘플은 포함된 각 명령의 통계에 귀속된다.",
            "- 명령별 샘플 수가 적으므로 0% 또는 100%를 "
            "일반화하지 않는다.",
            "- v0.6 결과 폴더를 test_result 아래에 추가하고 "
            "스크립트를 다시 실행하면 자동 반영된다.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """모든 분석 산출물을 생성한다."""
    arguments = parse_arguments()
    result_directories = discover_result_directories(
        arguments.results_root.resolve()
    )
    if not result_directories:
        raise FileNotFoundError(
            f"평가 결과 폴더를 찾을 수 없습니다: {arguments.results_root}"
        )

    output_directory = arguments.output_dir.resolve()
    csv_directory = output_directory / "csv"
    figure_directory = output_directory / "figures"
    report_directory = output_directory / "reports"

    metric_rows, improvement_rows = collect_version_metrics(
        result_directories
    )
    category_rows = collect_category_metrics(result_directories)
    command_rows = collect_command_metrics(result_directories)
    failure_rows = collect_failure_analysis(result_directories)
    training_rows = collect_training_curves(result_directories)
    metadata_rows = collect_experiment_metadata(
        result_directories,
        training_rows,
    )
    version_summary_rows = build_version_summary(
        metric_rows,
        metadata_rows,
    )

    write_csv(
        csv_directory / "version_metrics.csv",
        ["version", "benchmark_id", "phase", "samples", *METRIC_NAMES],
        metric_rows,
    )
    write_csv(
        csv_directory / "metric_improvements.csv",
        [
            "version",
            "benchmark_id",
            "metric",
            "baseline",
            "fine_tuned",
            "improvement_percentage_points",
        ],
        improvement_rows,
    )
    write_csv(
        csv_directory / "category_metrics.csv",
        [
            "version",
            "benchmark_id",
            "phase",
            "category",
            "samples",
            *METRIC_NAMES,
        ],
        category_rows,
    )
    write_csv(
        csv_directory / "command_metrics.csv",
        [
            "version",
            "benchmark_id",
            "phase",
            "command",
            "samples",
            "command_match",
            "parameter_match",
            "exact_match",
        ],
        command_rows,
    )
    write_csv(
        csv_directory / "failure_analysis.csv",
        [
            "version",
            "benchmark_id",
            "phase",
            "sample_index",
            "category",
            "input",
            "expected_status",
            "expected_commands",
            "failure_type",
            "prediction_raw",
        ],
        failure_rows,
    )
    write_csv(
        csv_directory / "training_curves.csv",
        [
            "version",
            "event_type",
            "step",
            "epoch",
            "loss",
            "eval_loss",
            "train_loss",
            "learning_rate",
            "grad_norm",
        ],
        training_rows,
    )
    write_csv(
        csv_directory / "experiment_metadata.csv",
        [
            "version",
            "training_source",
            "dataset",
            "train_samples",
            "validation_samples",
            "test_samples",
            "base_model",
            "initial_adapter",
            "epochs",
            "learning_rate",
            "batch_size",
            "gradient_accumulation_steps",
            "max_sequence_length",
            "random_seed",
            "lora_rank",
            "lora_alpha",
            "lora_dropout",
            "train_loss",
            "final_eval_loss",
            "gpu",
            "git_commit",
        ],
        metadata_rows,
    )
    write_csv(
        csv_directory / "version_summary.csv",
        [
            "version",
            "benchmark_id",
            "comparison_group",
            "training_source",
            "dataset",
            "train_samples",
            "epochs",
            "learning_rate",
            "command_accuracy",
            "parameter_accuracy",
            "exact_accuracy",
            "train_loss",
            "eval_loss",
        ],
        version_summary_rows,
    )

    plt = configure_matplotlib()
    chart_overall_accuracy(
        plt,
        metric_rows,
        figure_directory / "overall_accuracy.png",
    )
    chart_improvements(
        plt,
        improvement_rows,
        figure_directory / "improvement_comparison.png",
    )
    chart_command_accuracy(
        plt,
        command_rows,
        figure_directory / "command_accuracy.png",
    )
    chart_failure_distribution(
        plt,
        failure_rows,
        figure_directory / "failure_distribution.png",
    )
    chart_training_loss(
        plt,
        training_rows,
        figure_directory / "training_loss.png",
    )
    chart_final_eval_loss(
        plt,
        metadata_rows,
        figure_directory / "eval_loss.png",
    )
    chart_eval_loss_by_epoch(
        plt,
        training_rows,
        figure_directory / "eval_loss_by_epoch.png",
    )
    write_summary(
        report_directory / "analysis_summary.txt",
        metric_rows,
        improvement_rows,
        failure_rows,
        command_rows,
        metadata_rows,
    )

    print(f"분석한 버전: {', '.join(map(version_label, result_directories))}")
    print(f"분석 결과 저장: {output_directory}")


if __name__ == "__main__":
    main()
