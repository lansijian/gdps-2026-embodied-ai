# Reference: ROS 2 Foxy ament_python tutorial.
from glob import glob
from setuptools import setup
setup(name='cmd_vel_bridge', version='0.1.0', packages=['cmd_vel_bridge'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/cmd_vel_bridge']),
                  ('share/cmd_vel_bridge', ['package.xml']),
                  ('share/cmd_vel_bridge/launch', glob('launch/*.py')),
                  ('share/cmd_vel_bridge/config', glob('config/*')),
                  ('share/cmd_vel_bridge/scripts', glob('scripts/*'))],
      install_requires=['setuptools'], zip_safe=True,
      maintainer='GDPS contributors', maintainer_email='maintainers@example.com',
      description='Minimal G1 Foxy integration', license='Apache-2.0',
      entry_points={'console_scripts': ['bridge_node = cmd_vel_bridge.bridge_node:main']})
