#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_AUTOPILOT_DIR:-${HOME}/PX4-Autopilot}"
QGC_APPIMAGE="${QGC_APPIMAGE:-${HOME}/Downloads/QGroundControl-x86_64.AppImage}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

if [[ ! -d "${PX4_DIR}" ]]; then
  echo "오류: PX4 경로를 찾을 수 없습니다: ${PX4_DIR}" >&2
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

terminal_args=(
  --window
  --title="1 XRCE Agent"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; MicroXRCEAgent udp4 -p 8888; exec bash'"
  --tab
  --title="2 PX4 Gazebo"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PX4_DIR}\"; PX4_GZ_WORLD=default PX4_GZ_MODEL_POSE=0,0,0.30,0,0,0 make px4_sitl gz_x500; exec bash'"
  --tab
  --title="3 PX4 Adapter"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; ros2 run drone_control px4_takeoff_test; exec bash'"
  --tab
  --title="4 LLM Bridge"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; ros2 launch drone_llm llm_service.launch.py; exec bash'"
  --tab
  --title="5 Natural CLI"
  --command="bash -lc 'export ROS_DOMAIN_ID=${ROS_DOMAIN_ID}; cd \"${PROJECT_DIR}\"; source /opt/ros/humble/setup.bash; source install/local_setup.bash; until ros2 service type /ask_llm 2>/dev/null | grep -qx llm_ros2/srv/AskLLM; do sleep 1; done; echo \"LLM 첫 응답 예열 중...\"; ros2 service call /ask_llm llm_ros2/srv/AskLLM \"{question: 착륙해}\"; ros2 run drone_llm drone_cli; exec bash'"
)

if [[ -x "${QGC_APPIMAGE}" ]]; then
  terminal_args+=(
    --tab
    --title="6 QGroundControl"
    --command="bash -lc '\"${QGC_APPIMAGE}\"; exec bash'"
  )
else
  echo "경고: QGroundControl을 찾지 못해 실행하지 않습니다." >&2
fi

gnome-terminal "${terminal_args[@]}"