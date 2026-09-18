"""Qwen LLM 서비스를 YAML 파라미터와 함께 실행한다."""

from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    """LLM 서비스 노드를 위한 LaunchDescription을 생성한다."""
    config_path = PathJoinSubstitution(
        [
            FindPackageShare("drone_llm"),
            "config",
            "qwen.yaml",
        ]
    )
    llm_service_node = Node(
        package="drone_llm",
        executable="llm_service",
        name="llm_service",
        output="screen",
        parameters=[config_path],
    )

    return LaunchDescription([llm_service_node])
