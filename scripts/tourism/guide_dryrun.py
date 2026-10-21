#!/usr/bin/env python3
"""Dry-run the cultural-tourism guide workflow without ROS / camera / cloud.

Example:
    python3 scripts/tourism/guide_dryrun.py \
        --stations tracks/cultural-tourism/configs/stations.example.yaml \
        --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.example.json \
        --out /tmp/guide_dryrun.json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

import argparse
import json

from gdps_tourism.guide.dryrun import run_dry_tour


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run the tourism guide workflow")
    parser.add_argument("--stations", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--knowledge", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    summary = asyncio_run(
        run_dry_tour(
            Path(args.stations),
            knowledge_path=Path(args.knowledge) if args.knowledge else None,
            out_json=Path(args.out) if args.out else None,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["final_state"] == "finished" else 1


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


if __name__ == "__main__":
    raise SystemExit(main())
