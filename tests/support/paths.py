"""`import support.paths` puts ROOT/src (the taskloop package) on sys.path, once, ahead of everything else.

Every test module imports it, so a flat module can `from taskloop.contracts import ...` under any runner: the release shards,
`python3 tests/test_x.py`, `python3 -m unittest tests.test_x`, `just test`."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = str(ROOT / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
VENDOR = str(ROOT / "skills" / "task-loop" / "_vendor")  # the vendored shelf packages (dev/vendor.py) src imports by name
if VENDOR not in sys.path:
    sys.path.append(VENDOR)

if SRC not in os.environ.get("PYTHONPATH", "").split(os.pathsep):  # a child `python3 -m taskloop_dash` finds the package and the shelf
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [SRC, VENDOR, os.environ.get("PYTHONPATH")]))
