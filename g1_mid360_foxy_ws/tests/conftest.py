from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
for pkg in (ROOT/'src').iterdir():
    if (pkg/pkg.name).is_dir():
        sys.path.insert(0, str(pkg))
