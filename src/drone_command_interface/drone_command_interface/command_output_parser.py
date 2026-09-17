"""LLM의 문자열 출력을 안전한 드론 명령 객체로 변환한다."""

import json
from typing import Any

from jsonschema import Draft7Validator

from drone_command_interface.schemas import DRONE_COMMAND_SCHEMA


class InvalidModelOutputError(ValueError):
    """LLM 출력이 JSON 또는 드론 명령 스키마에 맞지 않을 때 발생한다."""


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """JSON 객체에 동일한 키가 두 번 나오면 파싱을 거부한다."""
    result: dict[str, Any] = {}

    for key, value in pairs:
        if key in result:
            raise InvalidModelOutputError(
                f"Duplicate JSON key is not allowed: {key}"
            )

        result[key] = value

    return result


def _reject_non_finite_number(value: str) -> None:
    """
    JSON 표준에 없는 NaN과 무한대 숫자를 거부한다.

    Python의 json 모듈은 기본적으로 NaN과 Infinity를 허용하지만,
    이런 값은 PX4 좌표나 거리 계산에 전달하면 안 된다.
    """
    raise InvalidModelOutputError(
        f"Non-finite JSON number is not allowed: {value}"
    )


def _format_validation_error(error: Any) -> str:
    """JSON Schema 오류 위치와 원인을 읽기 쉬운 문자열로 만든다."""
    path = ".".join(
        str(path_part)
        for path_part in error.absolute_path
    )

    if not path:
        path = "$"

    return f"{path}: {error.message}"


_VALIDATOR = Draft7Validator(DRONE_COMMAND_SCHEMA)


def parse_command_output(raw_output: str) -> dict[str, Any]:
    """
    LLM 문자열을 파싱하고 드론 명령 JSON Schema로 검증한다.

    마크다운 코드 블록이나 JSON 외부 설명은 허용하지 않는다.
    검증이 끝난 객체만 이후 Safety Validator와 실행기로 전달한다.
    잘못된 JSON, 중복 키 또는 스키마 오류가 있으면
    InvalidModelOutputError를 발생시킨다.
    """
    if not isinstance(raw_output, str):
        raise InvalidModelOutputError(
            "Model output must be a string"
        )

    stripped_output = raw_output.strip()

    if not stripped_output:
        raise InvalidModelOutputError(
            "Model output cannot be empty"
        )

    try:
        parsed_output = json.loads(
            stripped_output,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
        )
    except json.JSONDecodeError as error:
        raise InvalidModelOutputError(
            "Model output must contain exactly one valid JSON object"
        ) from error

    if not isinstance(parsed_output, dict):
        raise InvalidModelOutputError(
            "Top-level model output must be a JSON object"
        )

    validation_error = next(
        _VALIDATOR.iter_errors(parsed_output),
        None,
    )

    if validation_error is not None:
        formatted_error = _format_validation_error(
            validation_error
        )
        raise InvalidModelOutputError(
            f"Model output does not match the schema: {formatted_error}"
        )

    return parsed_output
