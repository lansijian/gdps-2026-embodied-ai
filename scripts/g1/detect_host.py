#!/usr/bin/env python3
"""Print local OS / WSL / ROS hints. Read-only."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        text = (out.stdout or "") + (out.stderr or "")
        return text.strip() or f"(exit {out.returncode})"
    except Exception as exc:
        return f"unavailable: {exc}"


def main() -> None:
    print("gdps_host_detection")
    print(f"python={sys.version.split()[0]}")
    print(f"platform={platform.platform()}")
    print(f"system={platform.system()}")
    print(f"machine={platform.machine()}")
    print(f"hostname={socket.gethostname()}")
    wsl = Path("/proc/version")
    if wsl.is_file() and "microsoft" in wsl.read_text(errors="ignore").lower():
        print("wsl=yes")
    else:
        print("wsl=no_or_unknown")
    print(f"ros2_on_path={'yes' if shutil.which('ros2') else 'no'}")
    opt_ros = Path("/opt/ros")
    print(f"opt_ros={list(p.name for p in opt_ros.iterdir()) if opt_ros.is_dir() else 'missing'}")
    if platform.system() == "Windows":
        print("--- powershell net ---")
        print(_run(["powershell", "-NoProfile", "-Command", "Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress | Format-Table -AutoSize | Out-String"]))
        print("--- wsl list ---")
        print(_run(["wsl", "-l", "-v"]))
    else:
        print("--- ip ---")
        print(_run(["ip", "-br", "addr"]))
    print(f"cwd={os.getcwd()}")


if __name__ == "__main__":
    main()
