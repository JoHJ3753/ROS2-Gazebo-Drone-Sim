from glob import glob
from os import path

from setuptools import find_packages
from setuptools import setup


package_name = "drone_llm"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        (
            path.join("share", package_name),
            ["package.xml"],
        ),
        (
            path.join("share", package_name, "config"),
            ["config/qwen.yaml"],
        ),
        (
            path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="hkit",
    maintainer_email="dongjae@example.com",
    description="Qwen-based ROS2 drone command service",
    license="Apache-2.0",
    extras_require={
        "test": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "llm_service = drone_llm.llm_service_node:main",
            "llm_client = drone_llm.llm_client:main",
        ],
    },
)
