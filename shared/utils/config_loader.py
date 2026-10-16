"""Load YAML or JSON config without requiring ROS 2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "README.md").is_file() and (parent / ".gitignore").is_file():
            return parent
    raise RuntimeError("Cannot locate repository root from shared.utils")


def load_mapping(path: str | Path) -> dict[str, Any]:
    """Load a mapping from `.yaml`/`.yml` (PyYAML) or `.json`."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    text = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            json_fallback = file_path.with_suffix(".json")
            if json_fallback.is_file():
                data = json.loads(json_fallback.read_text(encoding="utf-8"))
            else:
                raise ImportError(
                    f"PyYAML is required to read {file_path}. "
                    "Install pyyaml or provide a sibling .json file."
                ) from exc
        else:
            data = yaml.safe_load(text)
    else:
        raise ValueError(f"Unsupported config suffix: {suffix}")
    if not isinstance(data, Mapping):
        raise ValueError(f"Config root must be a mapping: {file_path}")
    return dict(data)
