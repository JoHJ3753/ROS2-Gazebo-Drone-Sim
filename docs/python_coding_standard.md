# Python Coding Standard

## 1. 기본 원칙

- Python 공식 스타일 가이드인 PEP 8을 기본으로 한다.
- 코드의 일관성과 가독성을 우선한다.
- 다른 팀원이 읽고 수정하기 쉬운 코드를 작성한다.
- 하나의 함수/클래스에 지나치게 많은 책임을 넣지 않는다.
- 중복 코드는 가능한 한 함수나 클래스로 분리한다.

## 2. 네이밍 규칙

### 파일명
`snake_case`를 사용한다.

```text
drone_control.py
mission_fsm.py
llm_client.py
action_history.py
```

### 변수 / 함수
`snake_case`를 사용한다.

```python
current_position = ...

def calculate_target_position():
    ...
```

### 클래스
`PascalCase`를 사용한다.

```python
class MissionFSM:
    ...

class DroneController:
    ...
```

### 상수
`UPPER_SNAKE_CASE`를 사용한다.

```python
MAX_ALTITUDE = 30.0
DEFAULT_ALTITUDE = 5.0
MAX_MOVE_DISTANCE = 20.0
```

## 3. 매직 넘버 금지

의미가 있는 숫자는 상수로 정의한다.

잘못된 예:
```python
if altitude > 30.0:
    ...
```

좋은 예:
```python
MAX_ALTITUDE = 30.0

if altitude > MAX_ALTITUDE:
    ...
```

단, `0`, `1`, 배열 인덱스 등 코드만 봐도 의미가 명확한 값은 허용한다.

## 4. 함수 작성

하나의 함수는 하나의 역할만 담당한다.

```python
def parse_command():
    ...

def validate_command():
    ...

def execute_command():
    ...
```

함수가 지나치게 커지면 기능별로 분리한다.

- 일반적으로 50줄 내외를 넘으면 분리할 수 있는지 검토한다.
- 100줄 이상의 함수는 특별한 이유가 없는 한 작성하지 않는다.

## 5. 타입 힌트

가능하면 함수 인자와 반환값에 타입 힌트를 사용한다.

```python
def calculate_distance(
    current_position: tuple[float, float],
    target_position: tuple[float, float],
) -> float:
    ...
```

## 6. Boolean / None 처리

Boolean 변수는 의미가 명확하게 작성한다.

```python
is_armed
is_connected
is_running
is_completed
has_error
```

`True`, `False`를 직접 비교하지 않는다.

```python
if is_armed:
    ...

if not is_armed:
    ...
```

`None` 비교는 `is` / `is not`을 사용한다.

```python
if command is None:
    ...
```

## 7. Import

Import는 파일 상단에 작성하고 다음 순서를 따른다.

1. Python 표준 라이브러리
2. 외부 라이브러리
3. ROS2 / 프로젝트 라이브러리

```python
import json
import math

import rclpy
from rclpy.node import Node

from drone_control.controller import DroneController
```

사용하지 않는 import와 `import *`는 사용하지 않는다.

## 8. 예외 처리와 로그

예외를 무시하지 않는다.

잘못된 예:
```python
try:
    execute_command()
except:
    pass
```

좋은 예:
```python
try:
    execute_command()
except ValueError as error:
    logger.error("Invalid command: %s", error)
```

ROS2에서는 `print()` 대신 ROS2 Logger를 사용한다.

```python
self.get_logger().info("Command received")
self.get_logger().warning("Invalid altitude")
self.get_logger().error("PX4 connection failed")
```

## 9. 주석

주석은 코드만 보고 알기 어려운 **이유나 의도**를 설명하는 데 사용한다.

```python
# PX4 NED 좌표계에서는 아래 방향이 +Z이므로
# 고도 5m는 z=-5.0으로 변환한다.
target_z = -altitude
```

단순히 코드 내용을 반복하는 주석은 작성하지 않는다.

드론 제어 및 좌표계 변환 코드에서는 축 방향과 yaw 부호를 주석 또는 상수로 명확히 표시한다.

## 10. LLM / FSM / Control 역할 분리

현재 프로젝트에서는 각 모듈의 책임을 명확하게 분리한다.

```text
LLM
→ 자연어 해석 및 Function Schema 생성

Function Schema
→ LLM과 ROS2 사이의 명령 인터페이스

Mission FSM
→ 명령 실행 순서와 상태 관리

Action History
→ 실제 수행된 명령 기록

Reverse Executor
→ Recall을 위한 역방향 명령 생성

Control Layer
→ 이동/회전/고도 제어 및 PX4 좌표 계산

PX4 Interface
→ PX4 Offboard 통신
```

LLM이 PX4 NED 좌표 계산이나 실제 드론 제어를 직접 수행하지 않는다.

```text
LLM
 ↓
Function Schema
 ↓
Mission FSM
 ↓
Control Layer
 ↓
PX4 Interface
 ↓
PX4
```

## 11. LLM 출력 검증

LLM의 출력은 항상 검증한 후 실행한다.

```text
LLM Output
    ↓
JSON Parse
    ↓
Schema Validation
    ↓
Command Validation
    ↓
Mission FSM
    ↓
Execution
```

LLM이 잘못된 값이나 존재하지 않는 명령을 생성할 수 있다는 것을 고려한다.

## 12. 코드 품질 도구

팀 전체에서 동일한 Formatter와 Linter를 사용한다.

### Formatter
`Black`

### Linter
`Ruff`

```bash
black .
ruff check .
```

설정은 프로젝트 파일로 통일한다.

## 13. 테스트

기능을 추가하거나 수정하면 관련 테스트를 확인한다.

테스트 프레임워크:

`pytest`

특히 다음 기능은 테스트를 우선한다.

- Function Schema 파싱
- 명령 검증
- FSM 상태 전환
- Action History
- Reverse Executor
- 잘못된 LLM 출력 처리

## 14. 팀 공통 핵심 규칙

1. 변수/함수는 `snake_case`
2. 클래스는 `PascalCase`
3. 상수는 `UPPER_SNAKE_CASE`
4. 매직 넘버는 사용하지 않는다.
5. 하나의 함수는 하나의 책임만 갖는다.
6. 타입 힌트를 적극적으로 사용한다.
7. ROS2에서는 Logger를 사용한다.
8. LLM / FSM / Control / PX4의 역할을 분리한다.
9. LLM 출력은 검증 후 실행한다.
10. 코드 수정 후 관련 테스트를 확인한다.
