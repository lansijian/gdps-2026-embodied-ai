#!/usr/bin/env python3
"""Read-only ROS 2 / environment probes for G1 PC2 (run on robot or via SSH).

Does not send motion commands. Timeout-bound listing helpers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import List


def run(cmd: List[str], timeout_s: float) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-4000:],
            "duration_s": time.time() - started,
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "error": "timeout", "duration_s": time.time() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description="GDPS QI read-only hardware probe")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--ros2", action="store_true", help="Run ros2 topic/introspection")
    args = parser.parse_args()
    report = {"generated_at": time.time(), "probes": []}
    report["probes"].append(run(["uname", "-a"], args.timeout))
    report["probes"].append(run(["python3", "--version"], args.timeout))
    if args.ros2:
        report["probes"].append(run(["ros2", "topic", "list"], args.timeout))
        report["probes"].append(run(["ros2", "topic", "list", "-t"], args.timeout))
        for topic in (
            "/dog_odom",
            "/utlidar/cloud_livox_mid360",
            "/tf",
            "/tf_static",
            "/joint_states",
        ):
            report["probes"].append(
                run(["ros2", "topic", "info", topic, "-v"], args.timeout)
            )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
