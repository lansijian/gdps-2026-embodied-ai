"""Merge missing audit fields without manufacturing verified physical facts."""
import copy
from pathlib import Path
import yaml
from .core import Blocked


def merge_site(value, defaults):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise Blocked('SITE_INVALID: expected a YAML mapping')
    result = copy.deepcopy(defaults)
    for key, item in value.items():
        if isinstance(result.get(key), dict) and isinstance(item, dict):
            result[key] = merge_site(item, result[key])
        else:
            result[key] = copy.deepcopy(item)
    return result


def default_path():
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory('g1_nav_config'))/'config/site.example.yaml'


def read_site(path):
    defaults = yaml.safe_load(default_path().read_text())
    site = merge_site(yaml.safe_load(Path(path).read_text()), defaults)
    if site.get('time_strategy'):
        site['timing']['strategy'] = site['time_strategy']
    return site
