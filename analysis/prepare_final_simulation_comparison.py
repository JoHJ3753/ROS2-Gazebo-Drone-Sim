"""단계별 시뮬레이션 로그를 공통 문항 비교 형식으로 정규화한다."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASELINE_MODEL_ID = "v0.1"
CANDIDATE_MODEL_ID = "v0.4"


@dataclass(frozen=True)
class CaseDefinition:
    """두 모델에서 동일하게 적용할 문항의 정답과 실행 기대값이다."""

    case_id: str
    input_text: str
    category: str
    expected_status: str
    expected_commands: list[dict[str, Any]]
    expected_runtime: str


def command(name: str, **arguments: Any) -> list[dict[str, Any]]:
    """단일 함수 호출 정답을 생성한다."""
    return [{"name": name, "arguments": arguments}]


CASES = (
    CaseDefinition("FLIGHT-01", "2미터 높이로 이륙해", "takeoff", "accepted", command("takeoff", altitude_m=2), "execute"),
    CaseDefinition("FLIGHT-02", "앞으로 1.5미터 이동해", "move", "accepted", command("move_drone", direction="forward", distance_m=1.5), "execute"),
    CaseDefinition("FLIGHT-03", "왼쪽으로 1미터 옮겨줘", "move", "accepted", command("move_drone", direction="left", distance_m=1), "execute"),
    CaseDefinition("FLIGHT-04", "뒤로 0.8미터 물러나", "move", "accepted", command("move_drone", direction="backward", distance_m=0.8), "execute"),
    CaseDefinition("FLIGHT-05", "오른쪽으로 1.2미터 이동해", "move", "accepted", command("move_drone", direction="right", distance_m=1.2), "execute"),
    CaseDefinition("FLIGHT-06", "현재 높이에서 0.5미터 상승해", "move", "accepted", command("move_drone", direction="up", distance_m=0.5), "execute"),
    CaseDefinition("FLIGHT-07", "기수를 왼쪽으로 45도 돌려", "rotate", "accepted", command("rotate_relative", yaw_deg=-45), "execute"),
    CaseDefinition("FLIGHT-08", "제자리에서 오른쪽으로 90도 회전해", "rotate", "accepted", command("rotate_relative", yaw_deg=90), "execute"),
    CaseDefinition("FLIGHT-09", "3초 동안 제자리에서 떠 있어", "hover", "accepted", command("hover", duration_s=3), "execute"),
    CaseDefinition("FLIGHT-10", "앞으로 일 점 이 미터만 가줘", "spoken_decimal", "accepted", command("move_drone", direction="forward", distance_m=1.2), "execute"),
    CaseDefinition("FLIGHT-11", "왼쪽으로 1미터 가부러", "dialect", "accepted", command("move_drone", direction="left", distance_m=1), "execute"),
    CaseDefinition("FLIGHT-12", "왔던 경로로 되돌아가", "recall", "accepted", command("recall"), "execute"),
    CaseDefinition("FLIGHT-13", "60초 동안 제자리에 떠 있어", "cancel_sequence", "accepted", command("hover", duration_s=60), "interrupt"),
    CaseDefinition("FLIGHT-14", "현재 동작을 즉시 취소해", "cancel_sequence", "accepted", command("cancel"), "execute"),
    CaseDefinition("FLIGHT-15", "지금 착륙해", "land", "accepted", command("land"), "execute"),
    CaseDefinition("EMERGENCY-01-TAKEOFF", "2미터 높이로 이륙해", "emergency_setup", "accepted", command("takeoff", altitude_m=2), "execute"),
    CaseDefinition("EMERGENCY-01-STOP", "드론을 즉시 비상 정지해", "emergency", "accepted", command("emergency_stop"), "execute"),
    CaseDefinition("EMERGENCY-02-TAKEOFF", "2미터 높이로 이륙해", "emergency_priority_setup", "accepted", command("takeoff", altitude_m=2), "execute"),
    CaseDefinition("EMERGENCY-02-STOP", "사진은 찍지 말고 즉시 비상 정지해", "emergency_priority", "accepted", command("emergency_stop"), "execute"),
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL 파일의 비어 있지 않은 행을 읽는다."""
    records = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def read_baseline_records(root: Path) -> list[dict[str, Any]]:
    """v0.1의 선별된 정상 비행 및 비상 정지 기록을 결합한다."""
    paths = (
        root / "stage_03_05" / "curated_results.jsonl",
        root / "stage_06" / "simulation_results.jsonl",
        root / "stage_07" / "simulation_results.jsonl",
    )
    return [record for path in paths for record in read_jsonl(path)]


def read_candidate_records(root: Path) -> list[dict[str, Any]]:
    """v0.4의 시간순 실행 폴더에 있는 기록을 결합한다."""
    paths = sorted(root.glob("*/simulation_results.jsonl"))
    return [record for path in paths for record in read_jsonl(path)]


def normalize_records(
    records: list[dict[str, Any]],
    model_id: str,
) -> list[dict[str, Any]]:
    """실행 순서에 따라 고유 문항 ID와 공통 정답을 부여한다."""
    if len(records) != len(CASES):
        raise ValueError(
            f"{model_id}: 예상 {len(CASES)}건, 실제 {len(records)}건입니다."
        )
    normalized = []
    for record, case in zip(records, CASES):
        actual_input = record.get("natural_language_input")
        if actual_input != case.input_text:
            raise ValueError(
                f"{model_id} / {case.case_id}: 문항 불일치 "
                f"(예상={case.input_text!r}, 실제={actual_input!r})"
            )
        updated = dict(record)
        updated.update(
            {
                "model_id": model_id,
                "case_id": case.case_id,
                "category": case.category,
                "expected_status": case.expected_status,
                "expected_commands": case.expected_commands,
                "expected_runtime": case.expected_runtime,
            }
        )
        normalized.append(updated)
    return normalized


def write_run(output_directory: Path, records: list[dict[str, Any]]) -> None:
    """기존 분석기와 호환되는 manifest와 JSONL을 저장한다."""
    output_directory.mkdir(parents=True, exist_ok=True)
    model_id = records[0]["model_id"]
    manifest = {
        "model_id": model_id,
        "source": "normalized_final_evaluation",
        "case_count": len(records),
        "note": "원본 로그를 수정하지 않고 공통 19개 실행만 정규화함",
    }
    (output_directory / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_directory / "simulation_results.jsonl").open(
        "w", encoding="utf-8"
    ) as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare_comparison(
    baseline_root: Path,
    candidate_root: Path,
    output_root: Path,
) -> tuple[Path, Path]:
    """두 모델의 단계별 로그를 비교 가능한 두 실행 폴더로 만든다."""
    baseline = normalize_records(
        read_baseline_records(baseline_root), BASELINE_MODEL_ID
    )
    candidate = normalize_records(
        read_candidate_records(candidate_root), CANDIDATE_MODEL_ID
    )
    baseline_output = output_root / "normalized_v0.1"
    candidate_output = output_root / "normalized_v0.4"
    write_run(baseline_output, baseline)
    write_run(candidate_output, candidate)
    return baseline_output, candidate_output


def main() -> None:
    """CLI 인자를 읽어 정규화된 비교 입력을 생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_comparison(
            args.baseline_root,
            args.candidate_root,
            args.output_root,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
