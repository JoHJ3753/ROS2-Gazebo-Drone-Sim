from setuptools import find_packages, setup

package_name = 'sample_call'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),

        # ROS 2 실행 시 qwen.yaml을 설치된 패키지에서도
        # 사용할 수 있도록 share 디렉터리에 함께 설치한다.
        ('share/' + package_name + '/config',
            ['config/qwen.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hkit',
    maintainer_email='dongjae@example.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            "sample_call = sample_call.sample_call:main",
            "llm_client = sample_call.llm_client:main",
        ],
    },
)
