# 🚁 ROS2-Gazebo-Drone-Sim

## 🚁 프로젝트 소개

자연어 드론 명령을 구조화된 함수 호출로 변환하고, ROS 2와 PX4 Offboard 제어를 통해 Gazebo 드론 시뮬레이터에서 실행하는 연구 프로젝트입니다.

사용자가 다음과 같은 자연어 명령을 입력하면 LLM이 이를 함수 스키마 형식의 JSON 명령으로 변환합니다.

```text
이륙해
앞으로 1m 이동해
오른쪽으로 90도 회전해
착륙해
```

생성된 명령은 JSON Schema와 명령 실행기의 검증을 통과한 경우에만 PX4 제어 계층으로 전달됩니다.

Qwen2.5 기반 명령 해석, JSON Schema 검증, 명령 실행, 임무 상태 관리, PX4 좌표 이동 및 상대 회전 기능을 각각 모듈화하여 개발하고 있습니다. 최종적으로는 Jetson Orin NX에서 명령 해석과 제어 노드를 구동하는 온디바이스 시스템을 목표로 합니다.

> 현재 프로젝트는 PX4 SITL과 Gazebo를 사용하는 시뮬레이션 검증 단계입니다.  
> 실기체에 적용하기 전 별도의 하드웨어 안전장치와 충분한 비행 검증이 필요합니다.

## 👥 프로젝트 정보

| 역할 | 담당자 |
|---|---|
| 조장 | 정윤상 |
| VLA 파인튜닝 | 권동재, 조용만 |
| 함수 스키마 및 드론 제어 | 조현준 |
| 지도강사 | 박승휘 |

## 📌 Git Commit Convention

| Prefix | 설명 |
|---|---|
| `[feature]` | 새로운 기능 또는 알고리즘 추가 |
| `[bugfix]` | 기존 기능의 오류 수정 |
| `[ignore]` | 주석, 문서, 코드 정리 등 동작에 영향을 주지 않는 변경 |

커밋 메시지 예시:

```bash
git commit -m "[feature] PX4 상대 회전 기능 추가"
git commit -m "[bugfix] 목표 고도 판정 오류 수정"
git commit -m "[ignore] README 프로젝트 가이드 및 개발 일지 추가"
```

## 📚 목차

- [프로젝트 목표](#-프로젝트-목표)
- [현재 구현 상태](#-현재-구현-상태)
- [시스템 구조](#️-시스템-구조)
- [자연어 명령 처리 흐름](#️-자연어-명령-처리-흐름)
- [주요 기능](#-주요-기능)
- [프로젝트 구조](#-프로젝트-구조)
- [환경 요구 사항](#-환경-요구-사항)
- [설치 및 빌드](#️-설치-및-빌드)
- [시뮬레이터 실행](#-시뮬레이터-실행)
- [런타임 PX4 명령 실행](#️-런타임-px4-명령-실행)
- [기존 비행 기능 검증 결과](#-기존-비행-기능-검증-결과)
- [LLM 서비스 실행](#-llm-서비스-실행)
- [학습 및 평가](#-학습-및-평가)
- [온디바이스 배포 범위](#-온디바이스-배포-범위)
- [안전 설계](#️-안전-설계)
- [테스트](#-테스트)
- [개발 일지](#-개발-일지)
- [관련 문서](#-관련-문서)
- [참고 저장소](#-참고-저장소)
- [향후 계획](#-향후-계획)
- [주의사항](#️-주의사항)

## 🎯 프로젝트 목표

사용자의 자연어 명령을 다음 흐름으로 처리하는 드론 제어 시스템을 구현합니다.

```text
사용자 자연어 명령
        |
        v
Qwen2.5 기반 LLM 서비스
        |
        v
함수 스키마 형식의 JSON 출력
        |
        v
출력 파서 및 JSON Schema 검증
        |
        v
검증된 명령 전달
        |
        v
CommandExecutor
        |
        v
Mission FSM / PX4 Command Adapter
        |
        v
PX4 Offboard 제어 메시지
        |
        v
Micro XRCE-DDS
        |
        v
PX4 SITL + Gazebo 드론
```

LLM이 잘못된 문자열, 범위를 벗어난 숫자 또는 지원하지 않는 명령을 생성하더라도 해당 값이 바로 PX4로 전달되지 않도록 다음 계층을 분리합니다.

1. LLM 출력 생성
2. JSON 파싱
3. JSON Schema 검증
4. 명령 실행기 검증
5. 임무 상태 검사
6. PX4 비행 안전 검사
7. Offboard 명령 발행

## ✅ 현재 구현 상태

| 구분 | 상태 | 설명 |
|---|---|---|
| 드론 명령 JSON Schema | 완료 | 명령 이름, 인자, 응답 상태 검증 |
| LLM 출력 파서 | 완료 | 모델 원문 출력의 JSON 파싱 및 검증 |
| LoRA 학습·평가 파이프라인 | 완료 | Qwen2.5-3B-Instruct 기반 학습 및 비교 평가 |
| GGUF LLM 서비스 | 완료 | ROS 2 `/ask_llm` 서비스 제공 |
| Action History | 완료 | 성공적으로 실행된 명령 이력 저장 |
| Reverse Executor | 완료 | 실행 이력을 이용한 역방향 명령 생성 |
| Mission FSM | 완료 | 임무 상태와 상태 전환 조건 관리 |
| Coordinate Calculator | 완료 | 절대좌표 및 기수 기준 상대좌표 계산 |
| Yaw Calculator | 완료 | 상대 회전 목표와 최단 회전 오차 계산 |
| CommandExecutor | 완료 | 검증된 명령을 대응하는 비행 함수로 전달 |
| PX4 수직 이륙 | 완료 | 현재 수평 위치를 유지하며 목표 고도까지 이륙 |
| 홈 기준 절대좌표 이동 | 기능 검증 완료 | PX4 local NED 좌표 변환 및 이동 검증 |
| 기수 기준 상대이동 | 기능 검증 완료 | 앞·뒤·왼쪽·오른쪽 상대이동 검증 |
| 상대 Yaw 회전 | 기능 검증 완료 | 현재 기수 기준 좌우 회전 검증 |
| PX4 시작 안전 검사 | 완료 | 중복 제어 노드, 위치·속도·상태 검사 |
| 런타임 명령 대기 | 완료 | 안전 검사 후 자동 이륙하지 않고 `IDLE` 상태 대기 |
| JSON 기반 런타임 이륙 | 완료 | `/drone/validated_command`의 `takeoff` 명령으로 이륙 |
| 런타임 상대이동 연결 | 진행 중 | `CommandExecutor`와 상대이동 기능 연결 예정 |
| 런타임 상대회전 연결 | 진행 중 | `CommandExecutor`와 상대회전 기능 연결 예정 |
| 런타임 자동 착륙 | 진행 중 | ROS 명령 기반 PX4 착륙 및 Disarm 처리 예정 |
| LLM과 PX4 종단 간 연동 | 진행 중 | 파서 출력과 명령 토픽 연결 예정 |
| 복합 명령 순차 실행 | 예정 | 이전 명령 완료 후 다음 명령 실행 |
| 키보드 후보정 제어 노드 | 예정 | 자연어 이동 후 수동 미세 조정 |
| Vision/VLM 물체 접근 | 예정 | 카메라 또는 Depth 정보를 이용한 목표 접근 |
| Jetson Docker 배포 | 예정 | Jetson Orin NX 8GB 대상 컨테이너 구성 |

## 🏗️ 시스템 구조

```mermaid
flowchart TD
    A[사용자 자연어 명령] --> B[drone_llm]
    B --> C[Qwen2.5 GGUF 추론]
    C --> D[command_output_parser]
    D --> E{JSON Schema 검증}
    E -->|실패| F[실행 거부 및 오류 로그]
    E -->|성공| G[명령 연결 계층]
    G --> H[/drone/validated_command]
    H --> I[CommandExecutor]
    I --> J[Mission FSM]
    I --> K[Coordinate Calculator]
    I --> L[Yaw Calculator]
    J --> M[PX4 Command Adapter]
    K --> M
    L --> M
    M --> N[Micro XRCE-DDS]
    N --> O[PX4 SITL]
    O --> P[Gazebo]
    O --> Q[QGroundControl]
```

현재 다음 구간은 구현과 시뮬레이션 검증이 완료됐습니다.

```text
/drone/validated_command
→ CommandExecutor
→ PX4 Command Adapter
→ PX4 Offboard 수직 이륙
→ 목표 고도 호버링
```

다음 구간은 추가 개발 중입니다.

```text
사용자 키보드 입력
→ LLM 서비스
→ 출력 파서
→ /drone/validated_command
```

## ⌨️ 자연어 명령 처리 흐름

최종 목표는 다음과 같은 키보드 입력을 실제 비행 함수로 연결하는 것입니다.

```text
"2m 이륙해"
```

LLM이 생성해야 하는 명령:

```json
{
  "status": "accepted",
  "commands": [
    {
      "name": "takeoff",
      "arguments": {
        "altitude_m": 2.0
      }
    }
  ],
  "message": ""
}
```

파서는 전체 응답을 검증하고, 실행 계층에는 개별 명령을 전달합니다.

```json
{
  "name": "takeoff",
  "arguments": {
    "altitude_m": 2.0
  }
}
```

`CommandExecutor`는 명령 이름과 인자를 다시 검사한 뒤 PX4 명령 어댑터의 대응 함수를 호출합니다.

현재 `CommandExecutor`가 연결할 수 있도록 정의된 명령은 다음과 같습니다.

```text
arm
disarm
takeoff
land
move_drone
rotate_relative
hover
```

현재 실제 런타임 PX4 연결이 완료된 명령은 `takeoff`입니다. 나머지 명령은 단계적으로 연결하고 있습니다.

## ✨ 주요 기능

### 명령 스키마

현재 스키마에서 정의하는 명령은 다음과 같습니다.

| 명령 | 설명 |
|---|---|
| `arm` | 모터 활성화 |
| `disarm` | 모터 비활성화 |
| `takeoff` | 지정한 고도까지 이륙 |
| `land` | 착륙 |
| `move_drone` | 기수 기준 방향과 거리만큼 이동 |
| `move_clock_direction` | 시계 방향 기준 이동 |
| `rotate_relative` | 현재 기수 기준 상대 회전 |
| `hover` | 현재 위치 유지 |
| `take_photo` | 사진 촬영 요청 |
| `return_home` | 저장된 홈 좌표로 직접 복귀 |
| `recall` | 실행 이력을 역순으로 따라 복귀 |
| `cancel` | 대기 중인 명령 취소 |
| `emergency_stop` | 비상 정지 |

모델 응답 상태는 다음 네 가지로 구분합니다.

| 상태 | 의미 |
|---|---|
| `accepted` | 실행 가능한 명령 |
| `clarification_required` | 거리·높이·각도 등의 추가 정보 필요 |
| `unsupported` | 현재 지원하지 않는 드론 기능 |
| `invalid` | 드론 명령으로 판단할 수 없는 입력 |

### CommandExecutor

`CommandExecutor`는 검증된 단일 명령을 대응하는 비행 함수로 전달합니다.

주요 검증 항목:

- 명령 객체의 `name`, `arguments` 구조 검사
- 지원하지 않는 명령 거부
- 필수 인자 누락 검사
- 정의되지 않은 추가 인자 거부
- 불리언을 숫자로 사용하는 입력 거부
- `NaN`, `Infinity` 등 비유한 숫자 거부
- 0 이하의 거리·고도·속도·시간 거부
- 지원하지 않는 이동 방향 거부
- 잘못된 명령이 비행 함수에 전달되지 않았는지 검사

한 번에 한 명령만 비행 함수에 전달합니다. 여러 명령을 동시에 PX4에 발행하지 않도록 복합 명령의 순차 실행은 별도 조정 계층에서 처리할 예정입니다.

### PX4 좌표계

PX4는 NED 좌표계를 사용합니다.

| 축 | 양의 방향 |
|---|---|
| X | 북쪽 |
| Y | 동쪽 |
| Z | 아래쪽 |

따라서 상승할 때는 Z 값이 감소하고, 하강할 때는 Z 값이 증가합니다.

### 좌표 이동

- 홈 위치 기준 절대좌표 이동
- 현재 기수 기준 상대이동
- 앞·뒤·왼쪽·오른쪽·위·아래 이동
- 이륙 후 수평 이동을 수행하는 단계별 제어
- 목표 위치 도달 오차 검사
- 현재 좌표와 목표 좌표 로그 출력

### 상대 회전

- 현재 heading을 기준으로 목표 yaw 계산
- 오른쪽 회전은 양수 각도
- 왼쪽 회전은 음수 각도
- ±180도 경계에서 최단 회전 오차 계산
- 목표 yaw 도달 후 위치 및 기수 유지

### 런타임 명령 대기

PX4 명령 어댑터는 실행 직후 자동 이륙하지 않습니다.

```text
PX4 위치 및 상태 수신
→ 사전 비행 안전 검사
→ 2초 연속 안정성 검사
→ IDLE 상태
→ 검증된 명령 대기
```

준비 완료 시 다음 로그가 출력됩니다.

```text
Vehicle data is stable. Waiting for a validated command.
```

## 📁 프로젝트 구조

```text
ROS2-Gazebo-Drone-Sim/
├── data/
│   ├── dataset_v0.1/
│   ├── dataset_v0.2/
│   ├── dataset_v0.3/
│   └── dataset_v0.4/
├── docs/
│   └── python_coding_standard.md
├── model/
│   └── Qwen2.5-3B-Instruct-Q4_K_M.gguf
├── src/
│   ├── drone_command_interface/
│   │   ├── drone_command_interface/
│   │   │   ├── prompts/
│   │   │   ├── schemas/
│   │   │   └── command_output_parser.py
│   │   ├── package.xml
│   │   └── setup.py
│   ├── drone_control/
│   │   ├── drone_control/
│   │   │   ├── action_history.py
│   │   │   ├── command_executor.py
│   │   │   ├── coordinate_calculator.py
│   │   │   ├── mission_fsm.py
│   │   │   ├── px4_command_adapter.py
│   │   │   ├── reverse_executor.py
│   │   │   └── yaw_calculator.py
│   │   ├── package.xml
│   │   ├── setup.py
│   │   └── test/
│   ├── drone_llm/
│   │   ├── config/
│   │   │   └── qwen.yaml
│   │   ├── drone_llm/
│   │   │   ├── llm_client.py
│   │   │   └── llm_service_node.py
│   │   ├── launch/
│   │   │   └── llm_service.launch.py
│   │   ├── package.xml
│   │   └── setup.py
│   ├── llm_ros2/
│   │   ├── srv/
│   │   │   └── AskLLM.srv
│   │   ├── CMakeLists.txt
│   │   └── package.xml
│   ├── px4_msgs/
│   ├── drone_interfaces/
│   ├── drone_simulation/
│   ├── mission_bringup/
│   └── target_vision/
├── test_result/
│   ├── test_result_v0.1/
│   ├── test_result_v0.2/
│   └── test_result_v0.3/
├── training/
│   ├── train.py
│   ├── inference.py
│   ├── evaluate.py
│   ├── experiment_logger.py
│   ├── README.md
│   └── requirements.txt
├── README.md
└── .gitignore
```

`build/`, `install/`, `log/` 디렉터리는 colcon 빌드 과정에서 생성되며 Git으로 관리하지 않습니다.

## 💻 환경 요구 사항

### 개발 및 시뮬레이션

- Ubuntu 22.04
- ROS 2 Humble
- Python 3.10
- PX4 Autopilot
- Gazebo Sim
- Micro XRCE-DDS Agent
- QGroundControl
- `px4_msgs`

### 모델 학습

- Python 가상환경 권장
- PyTorch
- Transformers
- Datasets
- PEFT
- Accelerate
- JSON Schema
- NVIDIA GPU 서버

학습 검증에는 KT Cloud A100 환경을 사용했습니다.

### 온디바이스 목표 환경

- Jetson Orin NX 8GB
- Ubuntu 22.04
- Docker 컨테이너
- ROS 2 Humble
- 로컬 GGUF 모델
- PX4와 연결 가능한 DDS 네트워크

## 🛠️ 설치 및 빌드

저장소를 복제합니다.

```bash
git clone https://github.com/JoHJ3753/ROS2-Gazebo-Drone-Sim.git
cd ROS2-Gazebo-Drone-Sim
```

ROS 2 환경을 불러오고 빌드합니다.

```bash
source /opt/ros/humble/setup.bash

colcon build --symlink-install

source install/local_setup.bash
```

특정 패키지만 빌드하려면 다음과 같이 실행합니다.

```bash
colcon build \
  --packages-select drone_control \
  --symlink-install
```

LLM 실행에는 `llama-cpp-python`이 별도로 필요합니다. 설치 방법은 사용하는 CPU, CUDA 및 Jetson 환경에 맞게 선택해야 합니다.

## 🎮 시뮬레이터 실행

본 프로젝트의 PX4 ROS 2 통신에서는 다른 팀이나 장비의 ROS 2 노드가 섞이지 않도록 `ROS_DOMAIN_ID=42`를 사용합니다.

모든 관련 터미널에서 PX4, Agent 및 ROS 2 노드를 실행하기 전에 다음 값을 설정해야 합니다.

```bash
export ROS_DOMAIN_ID=42
```

### 1. Micro XRCE-DDS Agent

첫 번째 터미널에서 실행합니다.

```bash
export ROS_DOMAIN_ID=42

MicroXRCEAgent udp4 -p 8888
```

### 2. PX4 SITL과 Gazebo

두 번째 터미널에서 실행합니다.

```bash
export ROS_DOMAIN_ID=42

cd ~/PX4-Autopilot

PX4_GZ_WORLD=default \
PX4_GZ_MODEL_POSE="0,0,0.30,0,0,0" \
make px4_sitl gz_x500
```

PX4 터미널에서 다음 로그가 출력될 때까지 기다립니다.

```text
Ready for takeoff!
time sync converged
```

PX4의 `pxh>`에서 DDS Domain을 확인할 수 있습니다.

```text
param show UXRCE_DDS_DOM_ID
```

값이 42가 아니라면 다음과 같이 설정하고 PX4를 재시작합니다.

```text
param set UXRCE_DDS_DOM_ID 42
param save
```

### 3. QGroundControl

세 번째 터미널에서 설치된 AppImage 경로에 맞게 실행합니다.

```bash
./QGroundControl-x86_64.AppImage
```

QGroundControl은 PX4 연결 상태, 비행 모드, 고도, 방향 및 착륙 상태를 확인하는 용도로 사용합니다.

### 4. ROS 2 통신 확인

새 터미널에서 실행합니다.

```bash
export ROS_DOMAIN_ID=42

cd ROS2-Gazebo-Drone-Sim

source /opt/ros/humble/setup.bash
source install/local_setup.bash

ros2 topic list | grep '^/fmu/'
ros2 node list
```

## 🛩️ 런타임 PX4 명령 실행

### 1. PX4 명령 어댑터 실행

```bash
export ROS_DOMAIN_ID=42

cd ROS2-Gazebo-Drone-Sim

source /opt/ros/humble/setup.bash
source install/local_setup.bash

ros2 run drone_control px4_takeoff_test
```

어댑터는 PX4 상태가 안정될 때까지 기다립니다.

정상적인 준비 로그:

```text
Vehicle data is stable. Waiting for a validated command.
```

이 로그가 출력되기 전에는 비행 명령을 보내지 않습니다.

### 2. JSON 이륙 명령 전송

별도 터미널에서 실행합니다.

```bash
export ROS_DOMAIN_ID=42

cd ROS2-Gazebo-Drone-Sim

source /opt/ros/humble/setup.bash
source install/local_setup.bash

ros2 topic pub --once \
/drone/validated_command \
std_msgs/msg/String \
"{data: '{\"name\":\"takeoff\",\"arguments\":{\"altitude_m\":2.0}}'}"
```

정상적인 로그 흐름:

```text
Validated command received
Takeoff command accepted: altitude_m=2.00
Takeoff target prepared
Vehicle data is valid. Starting setpoint stream
Requested Offboard mode and vehicle arm
Offboard mode enabled and vehicle armed
Takeoff target reached. Holding current position and yaw.
```

2026년 9월 21일 시뮬레이션 검증에서 2m 이륙 명령을 전송했으며 QGroundControl에서 약 6.8ft의 고도를 확인했습니다.

```text
2.0m ≈ 6.56ft
```

QGroundControl 표시값과 목표값 사이의 수 cm 차이는 시뮬레이션 위치 추정, 표시 반올림 및 기체 기준점 차이로 발생할 수 있습니다.

### 3. 현재 단계의 착륙

런타임 `land` 함수 연결 전에는 PX4의 `pxh>`에서 수동으로 착륙합니다.

```text
commander land
```

정상적인 PX4 로그:

```text
Landing at current position
Landing detected
Disarmed by landing
```

2026년 9월 21일 검증에서 착륙, 지면 감지, 자동 Disarm 및 프로펠러 정지를 확인했습니다.

> 런타임 JSON `land` 명령은 현재 구현 중입니다.

## 🧭 기존 비행 기능 검증 결과

다음 기능은 ROS 2 파라미터 기반 독립 시험 단계에서 Gazebo 시뮬레이션 검증을 완료했습니다.

### 홈 기준 절대좌표 이동

- 이륙 시작 위치를 홈 원점으로 저장
- 북쪽·동쪽·고도 값을 PX4 local NED 목표로 변환
- 수직 이륙 후 목표 좌표로 이동
- 목표 오차 범위 진입 후 위치 유지

### 기수 기준 상대이동

지원 방향:

```text
forward
backward
left
right
up
down
```

- 이륙 완료 시점의 현재 위치 사용
- 현재 heading을 기준으로 상대 목표 계산
- 기수가 동쪽을 바라보는 경우 `forward`를 동쪽 이동으로 변환
- 목표 좌표 도달 후 위치 유지

### 상대 회전

- 현재 heading 기준 상대 yaw 목표 계산
- 오른쪽 90도 회전 검증
- 목표 yaw 도달 후 현재 위치와 기수 유지

이 기능들은 계산기와 PX4 상태 제어에서 검증됐으며, 현재 `/drone/validated_command` 런타임 명령으로 연결하는 작업을 진행하고 있습니다.

## 🧠 LLM 서비스 실행

LLM 설정은 다음 파일에서 관리합니다.

```text
src/drone_llm/config/qwen.yaml
```

주요 파라미터:

```yaml
model_path: "model/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
context_size: 16384
threads: 4
max_tokens: 256
timeout_seconds: 120
temperature: 0.0
```

LLM 서비스를 실행합니다.

```bash
cd ROS2-Gazebo-Drone-Sim

source /opt/ros/humble/setup.bash
source install/local_setup.bash

ros2 launch drone_llm llm_service.launch.py
```

별도 터미널에서 자연어 명령을 요청할 수 있습니다.

```bash
source /opt/ros/humble/setup.bash
source install/local_setup.bash

ros2 service call \
  /ask_llm \
  llm_ros2/srv/AskLLM \
  "{question: '앞으로 1m 이동해'}"
```

현재 LLM 서비스는 모델 원문 응답을 반환합니다.

다음 연결은 개발 중입니다.

```text
/ask_llm 응답
→ command_output_parser
→ commands 배열에서 명령 추출
→ /drone/validated_command 발행
```

## 🎓 학습 및 평가

학습 환경을 구성합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r training/requirements.txt
```

Qwen2.5-3B-Instruct 모델을 LoRA 방식으로 학습합니다.

```bash
python3 -m training.train \
  --model-name Qwen/Qwen2.5-3B-Instruct \
  --dataset-dir data/dataset_v0.4 \
  --output-root training/outputs
```

학습 과정:

1. Train, Validation, Test 데이터셋 검증
2. 원본 모델 기준 성능 평가
3. LoRA 파인튜닝
4. 파인튜닝 모델 평가
5. 학습 전후 결과 비교
6. 실패 명령 및 실험 설정 기록

GGUF 양자화 모델은 추론용이며 LoRA 학습에는 Hugging Face 원본 모델을 사용합니다.

## 📦 온디바이스 배포 범위

목표 장치는 Jetson Orin NX 8GB이며 Docker 컨테이너 기반 배포를 계획하고 있습니다.

### 온디바이스에 포함할 대상

```text
src/drone_command_interface/
src/drone_control/
src/drone_llm/
src/llm_ros2/
src/px4_msgs/
model/Qwen2.5-3B-Instruct-Q4_K_M.gguf
```

주요 역할:

| 경로 | 역할 |
|---|---|
| `drone_command_interface` | 시스템 프롬프트, 함수 스키마, 출력 검증 |
| `drone_llm` | 로컬 Qwen 모델 ROS 2 서비스 |
| `llm_ros2` | LLM 서비스 인터페이스 |
| `drone_control` | 명령 실행, 좌표 계산, FSM, 명령 이력, PX4 제어 |
| `px4_msgs` | PX4 ROS 2 메시지 정의 |
| `model` | 온디바이스 추론용 GGUF 모델 |

### 온디바이스에서 제외할 대상

```text
data/
training/
test_result/
build/
install/
log/
```

다음 프로그램은 시뮬레이션 개발 PC에서 사용하며 Jetson 배포 대상에 포함하지 않습니다.

- PX4 SITL
- Gazebo
- QGroundControl

실기체 단계에서는 Jetson이 PX4 비행 컨트롤러와 DDS로 통신하는 구조를 사용합니다.

## 🛡️ 안전 설계

### PX4 비행 시작 안전 검사

PX4 명령 어댑터는 자동 제어 시작 전에 다음 조건을 검사합니다.

- `ROS_DOMAIN_ID=42`
- PX4 위치 및 상태 메시지 수신 여부
- 오래된 위치 또는 상태 메시지 차단
- Disarmed 상태
- Failsafe 비활성 상태
- PX4 사전 비행 검사 통과
- 유효한 로컬 위치
- 유효한 수평·수직 속도
- 제한 범위 안의 수평·수직 속도
- 유한한 heading 값
- 2초 동안 heading 변화 안정성
- PX4 추정기 reset counter 안정성
- PX4 명령 토픽 중복 발행자 검사
- 실행 중 Offboard 또는 Armed 상태 소실 감지

안전 조건을 통과하기 전에는 자동으로 이륙하지 않고 `WAITING_FOR_READY` 상태를 유지합니다.

안전 조건을 통과하면 `IDLE` 상태로 전환하여 검증된 명령을 기다립니다.

### LLM 출력 및 명령 안전 검사

LLM 출력은 다음 검사를 통과해야 합니다.

- 정확히 하나의 JSON 객체인지 검사
- 중복 JSON 키 거부
- JSON 표준에 없는 비유한 숫자 거부
- JSON Schema 검증
- 지원하는 응답 상태 검사
- 지원하는 명령 이름 검사
- 필수 인자와 추가 인자 검사

`CommandExecutor`는 개별 명령을 다시 검사합니다.

따라서 LLM이 생성한 문자열이 검증 없이 직접 PX4에 전달되지 않습니다.

## 🧪 테스트

### 드론 제어 단위 테스트

```bash
cd src/drone_control

source /opt/ros/humble/setup.bash
source ../../install/local_setup.bash

/usr/bin/python3 -m pytest -q
```

### 명령 실행기 및 PX4 어댑터 집중 테스트

```bash
cd src/drone_control

/usr/bin/python3 -m pytest -q \
  test/test_px4_command_adapter.py \
  test/test_command_executor.py
```

2026년 9월 21일 검증 결과:

```text
87 passed
```

스타일 검사 결과:

```text
4 files checked
No problems found
```

검사 대상:

```text
drone_control/px4_command_adapter.py
drone_control/command_executor.py
test/test_px4_command_adapter.py
test/test_command_executor.py
```

### ROS 2 패키지 테스트

```bash
cd ROS2-Gazebo-Drone-Sim

source /opt/ros/humble/setup.bash
source install/local_setup.bash

colcon test \
  --packages-select drone_control \
  --event-handlers console_direct+

colcon test-result --verbose
```

2026년 9월 19일 전체 검증 기록:

```text
Summary: 14615 tests, 0 errors, 0 failures, 4733 skipped
```

## 📅 개발 일지

### 2026.09.15 — 프로젝트 기반 구성

- ROS 2 드론 프로젝트 초기 구조 생성
- Qwen2.5-3B-Instruct 모델 선정
- 드론 명령 함수 스키마 정의
- JSON Schema 검증 테스트 추가
- 홈 복귀, 경로 역추적, 취소 및 비상 정지 명령 구분
- GGUF 경량화 모델 준비

### 2026.09.16 — 임무 제어 계층 구현

- Action History 구현
- Reverse Executor 구현
- Mission FSM 상태 전환 구현
- ROS 2 패키지를 루트 `src/` 구조로 통합
- `px4_msgs` 인터페이스 추가
- 모델 경로를 사용자 환경에 독립적인 상대경로로 변경

### 2026.09.17 — LLM 및 PX4 제어 기반 구현

- PX4 Offboard 수직 이륙 제어 구현
- 홈 기준 절대좌표 계산 및 이동 제어 구현
- LLM 명령 출력 검증 파서 구현
- Qwen LoRA 학습·평가 파이프라인 구현
- LoRA 어댑터 추론 기능 구현
- 파서와 LoRA 추론 연결
- 기수 기준 상대좌표 계산 구현

### 2026.09.18 — 데이터셋 및 상대이동 확장

- 데이터셋 v0.2, v0.3, v0.4 제작
- 데이터셋 정답 기준 문서화
- 파인튜닝 결과 및 비교 로그 저장
- 공통 시스템 프롬프트 최적화
- LLM 서비스 패키지를 `drone_llm`으로 재구성
- PX4 기수 기준 상대이동 제어 구현
- Gazebo와 QGroundControl을 이용한 실제 이동 검증

### 2026.09.19 — 상대 회전 및 안전 검사

- 상대 yaw 계산기 구현
- 오른쪽·왼쪽 상대 회전 명령 추가
- Domain 42 기반 ROS 2 통신 분리
- 중복 PX4 제어 발행자 감지
- 위치·속도·heading 안정성 검사
- 메시지 최신성 및 Failsafe 검사
- Offboard 상태 소실 시 제어 메시지 발행 중단
- Gazebo에서 오른쪽 90도 회전 검증 완료

### 2026.09.21 — 명령 실행기 및 런타임 이륙 연결

- 검증된 단일 명령을 비행 함수로 전달하는 `CommandExecutor` 구현
- 지원하지 않는 명령과 잘못된 명령 인자 차단
- 명령 실행기 단위 테스트 38개 통과
- `/drone/validated_command` 토픽 구독 추가
- PX4 준비 직후 자동 이륙하던 구조 제거
- 안전 검사 완료 후 `IDLE` 상태에서 명령 대기
- JSON `takeoff` 명령을 PX4 Offboard 이륙 함수와 연결
- Gazebo 기본 월드의 `x500` 기체로 2m 수직 이륙 검증
- QGroundControl에서 약 6.8ft 고도 및 Offboard 상태 확인
- PX4 `commander land`로 착륙 감지와 자동 Disarm 확인
- 명령 실행기 및 PX4 어댑터 집중 테스트 87개 통과

## 📖 관련 문서

| 문서 | 설명 |
|---|---|
| [Python 코딩 표준](docs/python_coding_standard.md) | Python 코드 작성 및 검사 기준 |
| [학습 가이드](training/README.md) | Qwen2.5 LoRA 학습 및 평가 방법 |
| [데이터셋 v0.2](data/dataset_v0.2/README.md) | v0.2 데이터 구성과 정답 기준 |
| [데이터셋 v0.3](data/dataset_v0.3/README.md) | v0.3 데이터 구성과 정답 기준 |
| [데이터셋 v0.4](data/dataset_v0.4/README.md) | v0.4 데이터 구성과 정답 기준 |
| [v0.2 평가 결과](test_result/test_result_v0.2/comparison_report.txt) | 파인튜닝 전후 결과 비교 |
| [v0.3 평가 결과](test_result/test_result_v0.3/comparison_report.txt) | 파인튜닝 전후 결과 비교 |

추후 다음 문서를 `docs/`에 추가할 예정입니다.

- 전체 시스템 아키텍처
- PX4/Gazebo 실행 가이드
- 온디바이스 Docker 배포 가이드
- 시뮬레이션 검증 기록
- 발표용 시행착오 및 문제 해결 기록
- 키보드 후보정 제어 노드 사용법

## 🔗 참고 저장소

### 이전 기수 프로젝트

- [Criss-J/ws_ros2](https://github.com/Criss-J/ws_ros2)

### PX4 및 Gazebo

- [PX4 Autopilot](https://github.com/PX4/PX4-Autopilot)
- [PX4 ROS 2 Messages](https://github.com/PX4/px4_msgs)
- [PX4 ROS2 Gazebo Simulation Template](https://github.com/SathanBERNARD/PX4-ROS2-Gazebo-Drone-Simulation-Template)
- [QGroundControl](https://github.com/mavlink/qgroundcontrol)

### 모델 및 학습 도구

- [Qwen2.5](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)
- [Hugging Face Transformers](https://github.com/huggingface/transformers)
- [PEFT](https://github.com/huggingface/peft)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)

## 🔮 향후 계획

- [x] 검증된 명령을 비행 함수로 전달하는 CommandExecutor 구현
- [x] PX4 자동 이륙을 검증된 런타임 명령 방식으로 변경
- [x] JSON 기반 `takeoff` 명령 시뮬레이션 검증
- [ ] JSON 기반 `move_drone` 런타임 연결
- [ ] JSON 기반 `rotate_relative` 런타임 연결
- [ ] JSON 기반 `hover` 런타임 연결
- [ ] JSON 기반 `land` 및 자동 Disarm 처리
- [ ] LLM 검증 결과와 런타임 명령 토픽 연결
- [ ] Mission FSM과 PX4 실행 결과 연결
- [ ] 자연어 명령의 종단 간 시뮬레이션 검증
- [ ] 복합 명령 순차 실행
- [ ] 키보드 기반 후보정 제어 노드 추가
- [ ] 카메라 기반 빨간 물체 탐지
- [ ] Depth 카메라 기반 물체 거리 계산
- [ ] Vision-Language 명령 처리
- [ ] Jetson Orin NX용 Dockerfile 작성
- [ ] Jetson 8GB 환경에 맞춘 모델 및 프롬프트 경량화
- [ ] 실기체용 geofence 및 비상 정지 강화
- [ ] 비행 로그와 시행착오 문서화

## ⚠️ 주의사항

이 저장소는 학습 및 연구 목적의 시뮬레이션 프로젝트입니다.

실기체에 적용할 때는 다음 항목을 별도로 검증해야 합니다.

- 최대 고도와 이동 거리 제한
- Geofence
- 배터리 상태
- 통신 끊김 대응
- 하드웨어 비상 정지
- 센서 이상 및 위치 추정 실패
- 프로펠러 주변 안전 확보
- 조종자의 즉시 수동 개입 수단

LLM이 생성한 응답을 검증 없이 실제 비행 명령으로 사용해서는 안 됩니다.