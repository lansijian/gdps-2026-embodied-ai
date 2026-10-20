# Reference: ROS 2 Foxy ament_python tutorial.
from glob import glob
from setuptools import setup
setup(name='g1_nav_bringup', version='0.1.0', packages=['g1_nav_bringup'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/g1_nav_bringup']),
                  ('share/g1_nav_bringup', ['package.xml']),
                  ('share/g1_nav_bringup/launch', glob('launch/*.py')),
                  ('share/g1_nav_bringup/config', glob('config/*')),
                  ('share/g1_nav_bringup/scripts', glob('scripts/*'))],
      install_requires=['setuptools'], zip_safe=True,
      maintainer='GDPS contributors', maintainer_email='maintainers@example.com',
      description='Minimal G1 Foxy integration', license='Apache-2.0',
      entry_points={'console_scripts': ['odom_bridge = g1_nav_bringup.odom_bridge:main']})
