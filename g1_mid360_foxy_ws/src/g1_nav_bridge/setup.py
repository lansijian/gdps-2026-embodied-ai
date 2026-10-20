from setuptools import setup, find_packages
from glob import glob
from pathlib import Path
package_name = 'g1_nav_bridge'
data = [('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml'])]
for folder in ('launch', 'config', 'rviz', 'maps', 'behavior_trees'):
    for path in glob(folder + '/**/*', recursive=True):
        if Path(path).is_file():
            data.append(('share/' + package_name + '/' + str(Path(path).parent), [path]))
setup(name=package_name, version='0.1.0', packages=find_packages(),
      data_files=data, install_requires=['setuptools'], zip_safe=True,
      maintainer='GDPS', maintainer_email='maintainers@example.invalid',
      description='G1 MID-360 Foxy dry-run navigation; LIVE disabled', license='BSD-3-Clause',
      entry_points={'console_scripts': ['dry_bridge = g1_nav_bridge.bridge:main']})
