#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_AUTOPILOT_DIR:-${HOME}/PX4-Autopilot}"
QGC_APPIMAGE="${QGC_APPIMAGE:-${HOME}/Downloads/QGroundControl-x86_64.AppImage}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
GZ_ENV_FILE="${PX4_DIR}/build/px4_sitl_default/rootfs/gz_env.sh"
GZ_WORLD_FILE="${PX4_DIR}/Tools/simulation/gz/worlds/test_world.sdf"

if [[ ! -d "${PX4_DIR}" ]]; then
  echo "오류: PX4 경로를 찾을 수 없습니다: ${PX4_DIR}" >&2
  exit 1
fi

if [[ ! -f "${GZ_ENV_FILE}" ]]; then
  echo "오류: Gazebo 환경 파일을 찾을 수 없습니다: ${GZ_ENV_FILE}" >&2
  echo "PX4 SITL을 한 번 빌드한 뒤 다시 실행하세요." >&2
  exit 1
fi

if [[ ! -f "${GZ_WORLD_FILE}" ]]; then
  echo "오류: Gazebo world 파일을 찾을 수 없습니다: ${GZ_WORLD_FILE}" >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/install/local_setup.bash" ]]; then
  echo "오류: ROS 2 워크스페이스를 먼저 빌드해야 합니다." >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/model/v0.4-Q4_K_M.gguf" ]]; then
  echo "오류: v0.4 GGUF 모델을 찾을 수 없습니다." >&2
  exit 1
fi

if pgrep -x MicroXRCEAgent >/dev/null 2>&1; then
  echo "오류: MicroXRCEAgent가 이미 실행 중입니다." >&2
  exit 1
fi

if pgrep -f "px4_sitl_default/bin/px4" >/dev/null 2>&1; then
  echo "오류: PX4 SITL이 이미 실행 중입니다." >&2
  exit 1
fi

if pgrep -f "gz sim" >/dev/null 2>&1; then
  echo "오류: Gazebo가 이미 실행 중입니다." >&2
  exit 1
fi

terminal_args=(
  --window
  --title="1 XRCE Agent"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; MicroXRCEAgent udp4 -p 8888; exec bash'"

  --tab
  --title="2 LLM Warmup + Gazebo"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; until ros2 service type /ask_llm 2>/dev/null | grep -qx llm_ros2/srv/AskLLM; do sleep 1; done; echo \"LLM 첫 응답 예열 중...\"; time ros2 service call /ask_llm llm_ros2/srv/AskLLM \"{question: 착륙해}\"; echo \"LLM 예열 완료. Gazebo를 시작합니다.\"; source \"${GZ_ENV_FILE}\"; gz sim --verbose=1 -r \"${GZ_WORLD_FILE}\"; exec bash'"

  --tab
  --title="3 PX4"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; until gz service -l 2>/dev/null | grep -qx /world/test_world/create; do sleep 1; done; cd \"${PX4_DIR}\"; PX4_GZ_STANDALONE=1 PX4_GZ_WORLD=test_world PX4_GZ_MODEL_POSE=1.30,0.83,0.30,0,0,0 make px4_sitl gz_x500 & px4_pid=\$!; until gz model --list 2>/dev/null | grep -qx x500_0; do if ! kill -0 \"\${px4_pid}\" 2>/dev/null; then wait \"\${px4_pid}\"; exit \$?; fi; sleep 1; done; echo \"Gazebo x500_0 모델 생성 확인\"; wait \"\${px4_pid}\"; exec bash'"

  --tab
  --title="4 PX4 Adapter"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; ros2 run drone_control px4_takeoff_test; exec bash'"

  --tab
  --title="5 LLM Bridge"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; ros2 launch drone_llm llm_service.launch.py; exec bash'"

  --tab
  --title="6 Natural CLI"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; until ros2 node list 2>/dev/null | grep -qx /px4_command_adapter; do sleep 1; done; echo \"PX4 어댑터 준비 대기 중...\"; until ros2 topic echo --once /drone/flight_status std_msgs/msg/String 2>/dev/null | grep -q \"명령 대기 중: 기체 상태 정상\"; do sleep 1; done; ros2 run drone_llm drone_cli; exec bash'"
)

if [[ -x "${QGC_APPIMAGE}" ]]; then
  terminal_args+=(
    --tab
    --title="7 QGroundControl"
    --command="bash -lc 'source \"${GZ_ENV_FILE}\"; until gz service -l 2>/dev/null | grep -qx /world/test_world/create; do sleep 1; done; \"${QGC_APPIMAGE}\"; exec bash'"
  )
else
  echo "경고: QGroundControl을 찾지 못해 실행하지 않습니다." >&2
fi

gnome-terminal "${terminal_args[@]}"