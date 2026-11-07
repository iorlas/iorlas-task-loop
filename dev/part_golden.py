"""Write tests/contracts/golden/parts.json: the version, DDL fingerprint and record schemas of every declared factory.db part, and the
`history` of the fingerprints each version of a part stored.

    uv run python dev/part_golden.py

Run it after a change to a part (a table, a stored record) that came with a version bump of the part and a step: the golden test
(tests/contracts/test_dbparts_golden.py) fails until the file says what the code now declares. A version already in the history is
never rewritten: a part that changed without a version bump is refused here, not on a live start.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.append(str(ROOT / "skills" / "task-loop" / "_vendor"))

from taskloop.app.parts import STAGE_PARTS  # noqa: E402
from tlkernel import dbparts  # noqa: E402

if __name__ == "__main__":
    target = ROOT / "tests" / "contracts" / "golden" / "parts.json"
    old = json.loads(target.read_text()) if target.exists() else {}
    now = json.loads(json.dumps(dbparts.golden(STAGE_PARTS)))
    for name, part in now.items():
        past = old.get(name, {}).get("history", {})
        for version, seen in past.items():
            if version in part["history"] and part["history"][version] != seen:
                sys.exit(f"part {name} v{version} changed its tables or records: bump the part's version and add its step")
        part["history"] = {**past, **part["history"]}
    target.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n")
