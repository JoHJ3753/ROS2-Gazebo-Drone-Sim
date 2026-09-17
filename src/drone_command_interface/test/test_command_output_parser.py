"""LLM 출력 파싱과 드론 명령 스키마 검증을 테스트한다."""

import json

import pytest

from drone_command_interface.command_output_parser import (
    InvalidModelOutputError,
)
from drone_command_interface.command_output_parser import (
    parse_command_output,
)


def make_valid_takeoff_result() -> dict:
    """정상적인 이륙 명령 결과를 생성한다."""
    return {
        "status": "accepted",
        "commands": [
            {
                "name": "takeoff",
                "arguments": {
                    "altitude_m": 2.0,
                },
            },
        ],
        "message": None,
    }


def test_valid_command_output_is_parsed():
    """스키마에 맞는 JSON 문자열이 딕셔너리로 변환되는지 확인한다."""
    expected_result = make_valid_takeoff_result()
    raw_output = json.dumps(
        expected_result,
        ensure_ascii=False,
    )

    result = parse_command_output(raw_output)

    assert result == expected_result


def test_surrounding_whitespace_is_allowed():
    """JSON 객체 앞뒤의 단순 공백과 줄바꿈은 허용한다."""
    expected_result = make_valid_takeoff_result()
    raw_output = (
        "\n  "
        + json.dumps(expected_result, ensure_ascii=False)
        + "  \n"
    )

    result = parse_command_output(raw_output)

    assert result == expected_result


@pytest.mark.parametrize(
    "raw_output",
    [
        "",
        "   ",
    ],
)
def test_empty_model_output_is_rejected(raw_output):
    """빈 모델 출력을 거부하는지 확인한다."""
    with pytest.raises(
        InvalidModelOutputError,
        match="cannot be empty",
    ):
        parse_command_output(raw_output)


def test_non_json_output_is_rejected():
    """일반 설명문처럼 JSON이 아닌 출력을 거부한다."""
    with pytest.raises(
        InvalidModelOutputError,
        match="valid JSON object",
    ):
        parse_command_output("앞으로 이동하겠습니다.")


def test_markdown_code_block_is_rejected():
    """JSON을 감싼 마크다운 코드 블록도 실행하지 않는다."""
    raw_output = (
        "```json\n"
        + json.dumps(make_valid_takeoff_result())
        + "\n```"
    )

    with pytest.raises(
        InvalidModelOutputError,
        match="valid JSON object",
    ):
        parse_command_output(raw_output)


def test_json_array_is_rejected():
    """최상위 값이 JSON 객체가 아니면 거부한다."""
    with pytest.raises(
        InvalidModelOutputError,
        match="must be a JSON object",
    ):
        parse_command_output("[]")


def test_unknown_command_is_rejected():
    """스키마에 없는 명령 이름을 거부한다."""
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "fly_anywhere",
                "arguments": {},
            },
        ],
        "message": None,
    }

    with pytest.raises(
        InvalidModelOutputError,
        match="does not match the schema",
    ):
        parse_command_output(json.dumps(result))


def test_additional_argument_is_rejected():
    """명령 스키마에 정의되지 않은 인자를 거부한다."""
    result = make_valid_takeoff_result()
    result["commands"][0]["arguments"]["unknown_value"] = 1

    with pytest.raises(
        InvalidModelOutputError,
        match="does not match the schema",
    ):
        parse_command_output(json.dumps(result))


def test_cancel_cannot_be_combined_with_other_command():
    """cancel이 다른 실행 명령과 함께 있으면 거부한다."""
    result = {
        "status": "accepted",
        "commands": [
            {
                "name": "cancel",
                "arguments": {},
            },
            {
                "name": "land",
                "arguments": {},
            },
        ],
        "message": None,
    }

    with pytest.raises(
        InvalidModelOutputError,
        match="does not match the schema",
    ):
        parse_command_output(json.dumps(result))


def test_duplicate_json_key_is_rejected():
    """동일한 JSON 키가 반복되면 모호한 출력을 실행하지 않는다."""
    raw_output = (
        "{"
        '"status":"accepted",'
        '"status":"invalid",'
        '"commands":[],'
        '"message":"invalid"'
        "}"
    )

    with pytest.raises(
        InvalidModelOutputError,
        match="Duplicate JSON key",
    ):
        parse_command_output(raw_output)


@pytest.mark.parametrize(
    "invalid_number",
    [
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_non_finite_json_number_is_rejected(invalid_number):
    """유한하지 않은 JSON 숫자를 실행 명령으로 허용하지 않는다."""
    raw_output = (
        '{"status":"accepted",'
        '"commands":[{"name":"takeoff","arguments":{'
        f'"altitude_m":{invalid_number}'
        '}}],'
        '"message":null}'
    )

    with pytest.raises(
        InvalidModelOutputError,
        match="Non-finite JSON number",
    ):
        parse_command_output(raw_output)


@pytest.mark.parametrize(
    "raw_output",
    [
        None,
        {},
        [],
    ],
)
def test_non_string_model_output_is_rejected(raw_output):
    """문자열이 아닌 모델 출력을 파싱 전에 거부한다."""
    with pytest.raises(
        InvalidModelOutputError,
        match="must be a string",
    ):
        parse_command_output(raw_output)


def test_valid_clarification_result_is_parsed():
    """추가 질문 결과도 스키마에 맞으면 정상적으로 반환한다."""
    expected_result = {
        "status": "clarification_required",
        "commands": [],
        "message": "이동할 거리를 미터 단위로 입력해 주세요.",
    }

    result = parse_command_output(
        json.dumps(
            expected_result,
            ensure_ascii=False,
        )
    )

    assert result == expected_result
