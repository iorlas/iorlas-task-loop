"""python3 -m taskloop_dash [--port N] [--bind A,B] [--ports MODULE:FUNC]"""
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "skills" / "task-loop" / "_vendor"  # the shelf packages the contracts' stores import by name
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.append(str(VENDOR))

from taskloop_dash.cli import dash  # noqa: E402

if __name__ == "__main__":
    dash.main()
