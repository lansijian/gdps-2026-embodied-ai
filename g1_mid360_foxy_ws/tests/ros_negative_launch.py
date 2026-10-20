"""Actual installed Foxy launch must reject missing/unverified inputs and LIVE."""
import os
from pathlib import Path
import subprocess
import tempfile
import yaml

root=Path(__file__).resolve().parents[1]
site=root/'src/g1_nav_config/config/site.example.yaml'
cases=[(['mode:=live'],'LIVE_DISABLED'),([], 'SITE_MISSING'),
       (['site:='+str(site)],'BLOCKED_NEEDS_CALIBRATION')]
for flags,expected in cases:
    p=subprocess.run(['ros2','launch','g1_nav_bringup','g1_nav_bringup.launch.py']+flags,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
    assert p.returncode!=0 and expected in p.stdout,(flags,p.stdout)
    print('PASS installed launch fail-closed',expected)
