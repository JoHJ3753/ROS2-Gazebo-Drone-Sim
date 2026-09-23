"""두 모델의 시뮬레이션 비교 CSV를 발표용 그림으로 변환한다."""

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


ACCURACY_FIELDS = (
    ("command_correct_pct", "명령"),
    ("parameter_correct_pct", "파라미터"),
    ("end_to_end_correct_pct", "종단 간"),
)
STATE_ORDER = (
    "success",
    "safe_rejection",
    "interpretation_failure",
    "runtime_failure",
    "unavailable",
)
STATE_LABELS = {
    "success": "실행 성공",
    "safe_rejection": "안전 거부",
    "interpretation_failure": "해석 실패",
    "runtime_failure": "실행 실패",
    "unavailable": "측정 불가",
}
STATE_COLORS = {
    "success": "#009E73",
    "safe_rejection": "#0072B2",
    "interpretation_failure": "#D55E00",
    "runtime_failure": "#E69F00",
    "unavailable": "#9CA3AF",
}
OUTCOME_ORDER = (
    "improved",
    "both_correct",
    "both_incorrect",
    "regressed",
    "unscored",
)
OUTCOME_LABELS = {
    "improved": "개선",
    "both_correct": "모두 성공",
    "both_incorrect": "모두 실패",
    "regressed": "악화",
    "unscored": "채점 불가",
}
OUTCOME_COLORS = {
    "improved": "#009E73",
    "both_correct": "#56B4E9",
    "both_incorrect": "#E69F00",
    "regressed": "#D55E00",
    "unscored": "#9CA3AF",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    """UTF-8 CSV를 딕셔너리 목록으로 읽는다."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_bool(value: str | None) -> bool | None:
    """CSV의 불리언 문자열을 삼상 값으로 변환한다."""
    if value == "True":
        return True
    if value == "False":
        return False
    return None


def parse_float(value: str | None) -> float | None:
    """비어 있는 수치 필드를 None으로 변환한다."""
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def classify_case(row: dict[str, str]) -> str:
    """문항을 성공·안전 거부·해석 실패·실행 실패로 분류한다."""
    interpretation = parse_bool(row.get("interpretation_correct"))
    runtime = parse_bool(row.get("runtime_correct"))
    if interpretation is None or runtime is None:
        return "unavailable"
    if not interpretation:
        return "interpretation_failure"
    if not runtime:
        return "runtime_failure"
    if row.get("expected_runtime") == "reject":
        return "safe_rejection"
    return "success"


def configure_matplotlib() -> Any:
    """한글을 지원하는 비대화형 Matplotlib 환경을 구성한다."""
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/codex_matplotlib_cache")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    font_family = "DejaVu Sans"
    if font_path.is_file():
        font_manager.fontManager.addfont(str(font_path))
        font_family = font_manager.FontProperties(fname=str(font_path)).get_name()
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
    """현재 그림을 고해상도 PNG로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close()


def draw_model_dashboard(
    plt: Any,
    summaries: list[dict[str, str]],
    output_path: Path,
) -> None:
    """모델별 핵심 정확도를 묶은 막대그래프를 만든다."""
    import numpy as np

    figure, axis = plt.subplots(figsize=(12.8, 7.2))
    models = [row["model_id"] for row in summaries]
    model_labels = [
        f"{row['model_id']}\n(n={row.get('test_count', '-')})"
        for row in summaries
    ]
    positions = np.arange(len(models))
    width = 0.22
    colors = ("#0072B2", "#E69F00", "#7C3AED")
    for index, ((field, label), color) in enumerate(zip(ACCURACY_FIELDS, colors)):
        values = [parse_float(row.get(field)) or 0.0 for row in summaries]
        bars = axis.bar(
            positions + (index - 1) * width,
            values,
            width,
            label=label,
            color=color,
        )
        axis.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=10)
    axis.set_title("모델별 자연어 드론 제어 정확도", fontsize=18, pad=16)
    axis.set_ylabel("정확도 (%)")
    axis.set_xticks(positions, model_labels)
    axis.set_ylim(0, 110)
    axis.grid(axis="y", alpha=0.2)
    axis.legend(frameon=False, ncols=3, loc="upper center")
    save_figure(plt, output_path)


def draw_case_matrix(
    plt: Any,
    rows: list[dict[str, str]],
    models: list[str],
    output_path: Path,
) -> None:
    """고정 문항별 상태를 모델 간 행렬로 표시한다."""
    import numpy as np
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    case_ids = sorted({row["case_id"] for row in rows if row.get("case_id")})
    index = {(row["model_id"], row["case_id"]): row for row in rows}
    state_index = {state: position for position, state in enumerate(STATE_ORDER)}
    matrix = np.array(
        [
            [
                state_index[classify_case(index[(model, case_id)])]
                if (model, case_id) in index
                else state_index["unavailable"]
                for case_id in case_ids
            ]
            for model in models
        ]
    )
    figure, axis = plt.subplots(figsize=(16, 4.5))
    color_map = ListedColormap([STATE_COLORS[state] for state in STATE_ORDER])
    axis.imshow(matrix, aspect="auto", cmap=color_map, vmin=-0.5, vmax=4.5)
    axis.set_title("고정 문항별 시뮬레이션 결과", fontsize=18, pad=16)
    axis.set_xticks(range(len(case_ids)), case_ids, rotation=60, ha="right", fontsize=8)
    axis.set_yticks(range(len(models)), models)
    axis.set_xlabel("동일 문항 ID")
    axis.set_xticks(np.arange(-0.5, len(case_ids), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(models), 1), minor=True)
    axis.grid(which="minor", color="white", linewidth=1.2)
    axis.tick_params(which="minor", bottom=False, left=False)
    axis.legend(
        handles=[
            Patch(color=STATE_COLORS[state], label=STATE_LABELS[state])
            for state in STATE_ORDER
        ],
        frameon=False,
        ncols=len(STATE_ORDER),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.32),
    )
    figure.subplots_adjust(bottom=0.3)
    save_figure(plt, output_path)


def draw_failure_distribution(
    plt: Any,
    rows: list[dict[str, str]],
    models: list[str],
    output_path: Path,
) -> None:
    """모델별 결과 상태의 비율을 100% 누적 막대로 표시한다."""
    figure, axis = plt.subplots(figsize=(12.8, 7.2))
    left = [0.0] * len(models)
    for state in STATE_ORDER:
        values = []
        counts = []
        for model in models:
            model_states = [
                classify_case(row) for row in rows if row["model_id"] == model
            ]
            count = model_states.count(state)
            counts.append(count)
            values.append(100 * count / len(model_states) if model_states else 0.0)
        bars = axis.barh(
            models,
            values,
            left=left,
            color=STATE_COLORS[state],
            label=STATE_LABELS[state],
        )
        for bar, count, value in zip(bars, counts, values):
            if count and value >= 7:
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + bar.get_height() / 2,
                    f"{count}건\n({value:.0f}%)",
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if state != "unavailable" else "#111827",
                )
        left = [before + value for before, value in zip(left, values)]
    axis.set_title("모델별 실행 결과 구성", fontsize=18, pad=16)
    axis.set_xlabel("전체 문항 대비 비율 (%)")
    axis.set_xlim(0, 100)
    axis.legend(frameon=False, ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    save_figure(plt, output_path)


def draw_pair_outcomes(
    plt: Any,
    pairs: list[dict[str, str]],
    output_path: Path,
) -> None:
    """두 모델 사이의 문항별 개선과 악화 건수를 표시한다."""
    counts = Counter(row.get("outcome", "unscored") for row in pairs)
    labels = [OUTCOME_LABELS[outcome] for outcome in OUTCOME_ORDER]
    values = [counts[outcome] for outcome in OUTCOME_ORDER]
    figure, axis = plt.subplots(figsize=(12.8, 7.2))
    bars = axis.bar(
        labels,
        values,
        color=[OUTCOME_COLORS[outcome] for outcome in OUTCOME_ORDER],
    )
    axis.bar_label(bars, padding=4, fontsize=11)
    axis.set_title("동일 문항 기준 모델 변화", fontsize=18, pad=16)
    axis.set_ylabel("문항 수")
    axis.grid(axis="y", alpha=0.2)
    save_figure(plt, output_path)


def draw_latency_comparison(
    plt: Any,
    rows: list[dict[str, str]],
    models: list[str],
    output_path: Path,
) -> None:
    """모델별 LLM 및 전체 처리시간 분포를 나란히 표시한다."""
    figure, axes = plt.subplots(1, 2, figsize=(12.8, 6.4))
    for axis, field, title in (
        (axes[0], "llm_latency_seconds", "LLM 응답 지연"),
        (axes[1], "elapsed_seconds", "전체 처리시간"),
    ):
        values = [
            [
                value
                for row in rows
                if row["model_id"] == model
                if (value := parse_float(row.get(field))) is not None
            ]
            for model in models
        ]
        if any(values):
            plot = axis.boxplot(values, tick_labels=models, patch_artist=True)
            for patch, color in zip(plot["boxes"], ("#56B4E9", "#009E73")):
                patch.set_facecolor(color)
                patch.set_alpha(0.8)
        else:
            axis.text(
                0.5,
                0.5,
                "측정 가능한 데이터 없음",
                ha="center",
                va="center",
            )
            axis.set_xticks([])
        axis.set_title(title)
        axis.set_ylabel("초")
        axis.grid(axis="y", alpha=0.2)
    figure.suptitle("모델별 응답시간 분포", fontsize=18)
    save_figure(plt, output_path)


def write_representative_cases(
    path: Path,
    rows: list[dict[str, str]],
    pairs: list[dict[str, str]],
    models: list[str],
) -> None:
    """개선·악화 사례의 입출력과 실패 이유를 CSV로 저장한다."""
    selected = {
        row["case_id"]: row["outcome"]
        for row in pairs
        if row.get("outcome") in {"improved", "regressed"}
    }
    by_key = {(row["model_id"], row["case_id"]): row for row in rows}
    fields = [
        "case_id",
        "outcome",
        "natural_language_input",
        f"{models[0]}_response",
        f"{models[0]}_result",
        f"{models[0]}_failure_reason",
        f"{models[1]}_response",
        f"{models[1]}_result",
        f"{models[1]}_failure_reason",
    ]
    output_rows = []
    for case_id, outcome in selected.items():
        before = by_key.get((models[0], case_id), {})
        after = by_key.get((models[1], case_id), {})
        output_rows.append(
            {
                "case_id": case_id,
                "outcome": outcome,
                "natural_language_input": before.get("natural_language_input")
                or after.get("natural_language_input"),
                f"{models[0]}_response": before.get("llm_raw_response"),
                f"{models[0]}_result": before.get("result"),
                f"{models[0]}_failure_reason": before.get("failure_reason"),
                f"{models[1]}_response": after.get("llm_raw_response"),
                f"{models[1]}_result": after.get("result"),
                f"{models[1]}_failure_reason": after.get("failure_reason"),
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)


def create_visualizations(input_dir: Path, output_dir: Path) -> list[Path]:
    """분석 CSV를 읽어 시각화와 대표 사례 CSV를 생성한다."""
    case_rows = read_csv(input_dir / "case_scores.csv")
    summaries = read_csv(input_dir / "model_summary.csv")
    pairs = read_csv(input_dir / "paired_comparison.csv")
    models = [row["model_id"] for row in summaries]
    if len(models) != 2:
        raise ValueError(
            "시각화에는 정확히 두 모델의 요약이 필요합니다."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    plt = configure_matplotlib()
    outputs = [
        output_dir / "model_dashboard.png",
        output_dir / "case_comparison_matrix.png",
        output_dir / "failure_distribution.png",
        output_dir / "pair_outcomes.png",
        output_dir / "latency_comparison.png",
    ]
    draw_model_dashboard(plt, summaries, outputs[0])
    draw_case_matrix(plt, case_rows, models, outputs[1])
    draw_failure_distribution(plt, case_rows, models, outputs[2])
    draw_pair_outcomes(plt, pairs, outputs[3])
    draw_latency_comparison(plt, case_rows, models, outputs[4])
    representative_path = output_dir / "representative_cases.csv"
    write_representative_cases(representative_path, case_rows, pairs, models)
    outputs.append(representative_path)
    manifest_path = output_dir / "visualization_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "models": models,
                "case_count": len({row["case_id"] for row in case_rows}),
                "generated_files": [path.name for path in outputs],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    outputs.append(manifest_path)
    return outputs


def main() -> None:
    """CLI 인자를 읽어 발표용 시뮬레이션 비교 자료를 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    required = (
        "case_scores.csv",
        "model_summary.csv",
        "paired_comparison.csv",
    )
    missing = [name for name in required if not (args.input_dir / name).is_file()]
    if missing:
        parser.error(f"필수 CSV가 없습니다: {', '.join(missing)}")
    try:
        create_visualizations(args.input_dir, args.output_dir)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
