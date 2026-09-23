"""고정 시뮬레이션 문항의 모델별 성능을 CSV로 비교한다."""

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


def score_record(record: dict[str, Any]) -> dict[str, Any]:
    """LLM 해석과 실제 실행/안전 거부를 분리해 채점한다."""
    raw = record.get("llm_raw_response")
    try:
        response = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError:
        response = None
    expected_status = record.get("expected_status")
    expected_commands = record.get("expected_commands")
    interpretation_correct = None
    command_correct = None
    parameter_correct = None
    if expected_status is not None and expected_commands is not None:
        if isinstance(response, dict) and isinstance(response.get("commands"), list):
            actual_commands = response["commands"]
            command_correct = (
                response.get("status") == expected_status
                and [item.get("name") for item in actual_commands if isinstance(item, dict)]
                == [item.get("name") for item in expected_commands]
                and len(actual_commands) == len(expected_commands)
            )
            parameter_correct = (
                command_correct
                and [item.get("arguments") for item in actual_commands]
                == [item.get("arguments") for item in expected_commands]
            )
        else:
            command_correct = False
            parameter_correct = False
        interpretation_correct = (
            isinstance(response, dict)
            and response.get("status") == expected_status
            and response.get("commands") == expected_commands
        )
    expected_runtime = record.get("expected_runtime")
    runtime_correct = None
    if expected_runtime == "execute":
        runtime_correct = record.get("result") == "success"
    elif expected_runtime == "reject":
        runtime_correct = (
            record.get("result") == "rejected"
            and record.get("px4_command") is None
        )
    end_to_end_correct = (
        interpretation_correct and runtime_correct
        if interpretation_correct is not None and runtime_correct is not None
        else None
    )
    return {
        "model_id": record.get("model_id"),
        "case_id": record.get("case_id"),
        "category": record.get("category"),
        "test_id": record.get("test_id"),
        "natural_language_input": record.get("natural_language_input"),
        "expected_status": expected_status,
        "expected_commands": (
            json.dumps(
                expected_commands,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if expected_commands is not None
            else None
        ),
        "expected_runtime": expected_runtime,
        "llm_raw_response": raw,
        "interpretation_correct": interpretation_correct,
        "command_correct": command_correct,
        "parameter_correct": parameter_correct,
        "runtime_correct": runtime_correct,
        "end_to_end_correct": end_to_end_correct,
        "result": record.get("result"),
        "failure_stage": record.get("failure_stage"),
        "failure_reason": record.get("failure_reason"),
        "llm_latency_seconds": record.get("llm_latency_seconds"),
        "bridge_latency_seconds": record.get("bridge_latency_seconds"),
        "flight_latency_seconds": record.get("flight_latency_seconds"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "position_error_m": record.get("position_error_m"),
        "yaw_error_deg": record.get("yaw_error_deg"),
    }


def read_records(run_directory: Path) -> list[dict[str, Any]]:
    """한 실행의 JSONL 기록을 읽고 manifest 모델명을 보완한다."""
    manifest = json.loads((run_directory / "run_manifest.json").read_text(encoding="utf-8"))
    records = []
    with (run_directory / "simulation_results.jsonl").open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                record = json.loads(line)
                record["model_id"] = record.get("model_id") or manifest["model_id"]
                records.append(record)
    return records


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return round(100 * sum(values) / len(values), 2) if values else None


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """모델별 정확도와 지연시간 중앙값을 집계한다."""
    summaries = []
    for model_id in sorted({row["model_id"] for row in rows}):
        model_rows = [row for row in rows if row["model_id"] == model_id]
        summary: dict[str, Any] = {"model_id": model_id, "test_count": len(model_rows)}
        for field in (
            "command_correct", "parameter_correct", "interpretation_correct",
            "runtime_correct", "end_to_end_correct",
        ):
            summary[f"{field}_pct"] = _rate(model_rows, field)
        for field in ("llm_latency_seconds", "elapsed_seconds", "position_error_m"):
            values = [row[field] for row in model_rows if row[field] is not None]
            summary[f"{field}_median"] = round(statistics.median(values), 3) if values else None
        summaries.append(summary)
    return summaries


def compare_pairs(rows: list[dict[str, Any]], baseline: str, candidate: str) -> list[dict[str, Any]]:
    """공통 case_id를 기준으로 개선·악화 문항을 찾는다."""
    by_model: dict[str, dict[str, dict[str, Any]]] = {baseline: {}, candidate: {}}
    for row in rows:
        if row["model_id"] in by_model and row["case_id"]:
            if row["case_id"] in by_model[row["model_id"]]:
                raise ValueError(f"중복 case_id: {row['model_id']} / {row['case_id']}")
            by_model[row["model_id"]][row["case_id"]] = row
    comparisons = []
    common = by_model[baseline].keys() & by_model[candidate].keys()
    for case_id in sorted(common):
        before = by_model[baseline][case_id]["end_to_end_correct"]
        after = by_model[candidate][case_id]["end_to_end_correct"]
        if before is None or after is None:
            outcome = "unscored"
        elif before and after:
            outcome = "both_correct"
        elif not before and after:
            outcome = "improved"
        elif before and not after:
            outcome = "regressed"
        else:
            outcome = "both_incorrect"
        comparisons.append({"case_id": case_id, "baseline": baseline, "candidate": candidate, "outcome": outcome})
    return comparisons


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    """헤더가 포함된 UTF-8 CSV를 저장한다."""
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """두 실행의 문항별/요약/쌍별 비교 CSV를 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = read_records(args.baseline) + read_records(args.candidate)
    if not records:
        parser.error("두 실행 모두 테스트 기록이 없습니다.")
    baseline_records = read_records(args.baseline)
    candidate_records = read_records(args.candidate)
    if not baseline_records or not candidate_records:
        parser.error("각 실행에 최소 한 건의 테스트 기록이 필요합니다.")
    rows = [score_record(record) for record in records]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "case_scores.csv", rows, list(rows[0]) if rows else [])
    summaries = summarize(rows)
    write_csv(args.output_dir / "model_summary.csv", summaries, list(summaries[0]) if summaries else [])
    baseline_id = baseline_records[0]["model_id"]
    candidate_id = candidate_records[0]["model_id"]
    if baseline_id == candidate_id:
        parser.error("두 실행의 model_id가 동일합니다.")
    pairs = compare_pairs(rows, baseline_id, candidate_id)
    write_csv(args.output_dir / "paired_comparison.csv", pairs, list(pairs[0]) if pairs else ["case_id", "baseline", "candidate", "outcome"])


if __name__ == "__main__":
    main()
