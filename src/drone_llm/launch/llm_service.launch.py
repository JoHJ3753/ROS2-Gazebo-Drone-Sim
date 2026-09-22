"""Qwen LLM 서비스를 YAML 파라미터와 함께 실행한다."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
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
    command_bridge_node = Node(
        package="drone_llm",
        executable="command_bridge",
        name="command_bridge",
        output="screen",
    )
    simulation_test_logger_node = Node(
        package="drone_llm",
        executable="simulation_test_logger",
        name="simulation_test_logger",
        output="screen",
        parameters=[{
            "model_id": LaunchConfiguration("model_id"),
            "model_sha256": LaunchConfiguration("model_sha256"),
            "prompt_version": LaunchConfiguration("prompt_version"),
            "test_cases_file": LaunchConfiguration("test_cases_file"),
        }],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("model_id", default_value="unidentified"),
            DeclareLaunchArgument("model_sha256", default_value=""),
            DeclareLaunchArgument("prompt_version", default_value=""),
            DeclareLaunchArgument("test_cases_file", default_value=""),
            llm_service_node,
            command_bridge_node,
            simulation_test_logger_node,
        ]
    )
