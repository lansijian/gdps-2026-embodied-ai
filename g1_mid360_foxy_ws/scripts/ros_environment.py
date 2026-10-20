"""Pre-overlay entry: pure environment checks, no ROS/SDK initialization."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/g1_nav_perception'))
from g1_nav_perception.environment import main
if __name__ == '__main__':
    raise SystemExit(main())
