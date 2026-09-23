"""시뮬레이션 명령 한 건의 실행 결과를 구조화한다."""

import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PositionSnapshot:
    """PX4 Local NED 좌표와 기수 방향의 한 시점 값이다."""

    x: float
    y: float
    z: float
    yaw_rad: float


@dataclass
class SimulationTestRecord:
    """자연어 명령부터 PX4 결과까지의 단일 테스트 기록이다."""

    timestamp: str
    test_id: str
    natural_language_input: str
    llm_raw_response: str | None = None
    parsed_command: dict[str, Any] | None = None
    validation_result: str = "pending"
    bridge_result: str = "pending"
    px4_command: dict[str, Any] | None = None
    initial_position: PositionSnapshot | None = None
    target_position: PositionSnapshot | None = None
    final_position: PositionSnapshot | None = None
    elapsed_seconds: float | None = None
    result: str = "running"
    failure_stage: str | None = None
    failure_reason: str | None = None
    flight_status: str | None = None
    model_id: str | None = None
    case_id: str | None = None
    category: str | None = None
    expected_status: str | None = None
    expected_commands: list[dict[str, Any]] | None = None
    expected_runtime: str | None = None
    llm_latency_seconds: float | None = None
    bridge_latency_seconds: float | None = None
    flight_latency_seconds: float | None = None
    position_error_m: float | None = None
    yaw_error_deg: float | None = None

    def as_json_dictionary(self) -> dict[str, Any]:
        """JSON 직렬화가 가능한 사전으로 변환한다."""
        return asdict(self)


class JsonlTestWriter:
    """완료된 테스트 기록을 UTF-8 JSONL 파일에 추가한다."""

    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory
        self._output_directory.mkdir(parents=True, exist_ok=True)
        self._output_path = self._output_directory / "simulation_results.jsonl"

    @property
    def output_path(self) -> Path:
        """현재 결과 파일 경로를 반환한다."""
        return self._output_path

    def append(self, record: SimulationTestRecord) -> None:
        """테스트 기록을 한 줄의 JSON으로 저장한다."""
        with self._output_path.open("a", encoding="utf-8") as file:
            json.dump(
                record.as_json_dictionary(),
                file,
                ensure_ascii=False,
            )
            file.write("\n")


def make_run_directory(output_root: Path, started_at: datetime) -> Path:
    """실행 시각을 포함한 충돌 없는 결과 디렉터리를 만든다."""
    base_name = started_at.strftime("%Y-%m-%d_%H%M%S")
    candidate = output_root / base_name
    suffix = 1

    while candidate.exists():
        candidate = output_root / f"{base_name}_{suffix:02d}"
        suffix += 1

    return candidate


def load_test_cases(path: Path) -> dict[str, dict[str, Any]]:
    """자연어 입력으로 고정 평가 문항을 조회할 수 있게 읽는다."""
    cases: dict[str, dict[str, Any]] = {}
    case_ids: set[str] = set()
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            required = {
                "case_id",
                "input",
                "category",
                "expected_status",
                "expected_commands",
                "expected_runtime",
            }
            if not isinstance(case, dict) or not required.issubset(case):
                raise ValueError(f"{line_number}행: 평가 문항 필수 항목 누락")
            if case["expected_runtime"] not in {"execute", "reject"}:
                raise ValueError(f"{line_number}행: expected_runtime 오류")
            if case["input"] in cases or case["case_id"] in case_ids:
                raise ValueError(f"{line_number}행: 중복 입력 또는 case_id")
            cases[case["input"]] = case
            case_ids.add(case["case_id"])
    return cases


def calculate_pose_error(record: SimulationTestRecord) -> None:
    """목표와 최종 NED 좌표의 오차를 기록한다."""
    target = record.target_position
    final = record.final_position
    if target is None or final is None:
        return
    record.position_error_m = round(
        math.dist((target.x, target.y, target.z), (final.x, final.y, final.z)),
        3,
    )
    yaw_delta = final.yaw_rad - target.yaw_rad
    record.yaw_error_deg = round(
        abs(math.degrees(math.atan2(math.sin(yaw_delta), math.cos(yaw_delta)))),
        2,
    )


def classify_bridge_failure(status: str) -> tuple[str, str]:
    """브리지 거부 메시지를 실패 단계와 사유로 변환한다."""
    if "LLM" in status:
        return ("llm", status)
    if "PX4 어댑터" in status or "PX4" in status:
        return ("bridge", status)
    return ("schema_validation", status)


def is_success_status(status: str) -> bool:
    """현재 PX4 어댑터가 발행하는 완료 상태인지 확인한다."""
    success_prefixes = (
        "목표 고도 도달",
        "목표 위치 도달",
        "회전 완료",
        "호버링 완료",
        "호버링 유지 중",
        "착륙 완료",
        "동작 취소 완료",
        "이륙 대기 취소",
        "긴급 정지 완료",
        "시동 완료",
        "홈 복귀 완료",
    )
    return status.startswith(success_prefixes)


def is_failure_status(status: str) -> bool:
    """PX4 어댑터의 거부 또는 오류 상태인지 확인한다."""
    failure_prefixes = (
        "명령 거부",
        "비행 오류",
        "이륙 취소",
    )
    return status.startswith(failure_prefixes)
