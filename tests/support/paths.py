"""`import support.paths` puts ROOT/src (the taskloop package) on sys.path, once, ahead of everything else.

Every test module imports it, so a flat module can `from taskloop.contracts import ...` under any runner: the release shards,
`python3 tests/test_x.py`, `python3 -m unittest tests.test_x`, `just test`."""
import atexit
import os
import shutil
import stat
import sys
import tempfile
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


def _guard_bd() -> None:
    """A `bd` first on PATH that fails loudly: no test reaches a real tracker (a test that needs bd's answers uses support.tlbd or a
    FakeBeadStore)."""
    d = Path(tempfile.mkdtemp(prefix="tl-nobd-"))
    atexit.register(shutil.rmtree, d, True)
    stub = d / "bd"
    stub.write_text("#!/bin/sh\necho 'bd: the suite must not run a real bd (support.tlbd, FakeBeadStore)' >&2\nexit 99\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


if not os.environ.get("TL_NO_BD_GUARD"):
    _guard_bd()
