from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QI_ROOT = ROOT / "tracks" / "quality-inspection"
if str(QI_ROOT) not in sys.path:
    sys.path.insert(0, str(QI_ROOT))
