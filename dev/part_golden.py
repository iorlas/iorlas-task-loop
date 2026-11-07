"""Write tests/contracts/golden/parts.json: the version, DDL fingerprint and record schemas of every registered factory.db part.

    uv run python dev/part_golden.py

Run it after a change to a part (a table, a stored record) that came with a version bump of the part and a step: the golden test
(tests/contracts/test_dbparts_golden.py) fails until the file says what the code now declares.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.append(str(ROOT / "skills" / "task-loop" / "_vendor"))

from taskloop.app.land.store import LAND  # noqa: E402
from taskloop.contracts import dbparts, factoryparts  # noqa: E402

PARTS = (factoryparts.KV, LAND)  # a part registers when its module is imported, and an unused import does not import it

if __name__ == "__main__":
    (ROOT / "tests" / "contracts" / "golden" / "parts.json").write_text(json.dumps(dbparts.golden(), indent=1, sort_keys=True) + "\n")
