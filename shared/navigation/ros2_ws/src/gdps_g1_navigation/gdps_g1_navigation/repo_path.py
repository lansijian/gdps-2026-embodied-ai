from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_on_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "README.md").is_file() and (parent / "shared").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return parent
    raise RuntimeError("GDPS repo root not found; keep this package under shared/navigation/ros2_ws")
