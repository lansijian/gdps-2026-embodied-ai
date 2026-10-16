from glob import glob
import os

from setuptools import find_packages, setup

package_name = "gdps_g1_navigation"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="DHU AILAB",
    maintainer_email="ailab@dhu.edu.cn",
    description="Shared G1 EDU navigation nodes for GDPS 2026.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "cmdvel_bridge = gdps_g1_navigation.cmdvel_bridge_node:main",
            "scan_restamper = gdps_g1_navigation.scan_restamper_node:main",
            "odom_tf = gdps_g1_navigation.odom_tf_node:main",
            "local_navigator = gdps_g1_navigation.local_navigator_node:main",
            "heartbeat = gdps_g1_navigation.heartbeat_node:main",
        ],
    },
)
