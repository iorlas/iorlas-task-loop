"""The golden fingerprints: a change to a part's tables or records cannot reach main without a version bump of the part."""
import json
from pathlib import Path

import support.paths  # noqa: F401

from taskloop.app.land.store import LAND
from taskloop.contracts import dbparts, factoryparts

STAGE_PARTS = (factoryparts.KV, LAND)  # a part registers when its module is imported, and an unused import does not import it
GOLDEN = Path(__file__).parent / "golden" / "parts.json"
HINT = "bump the part's version, add its step, then run `uv run python dev/part_golden.py`"


def test_every_part_matches_its_golden_fingerprint():
    golden = json.loads(GOLDEN.read_text())
    now = json.loads(json.dumps(dbparts.golden()))
    assert set(now) == set(golden), f"parts added or removed: {HINT}"
    for name, want in golden.items():
        have = now[name]
        assert have["version"] == want["version"], f"part {name}: version changed, run `uv run python dev/part_golden.py`"
        assert have["ddl"] == want["ddl"], f"part {name}: its tables changed without a version bump: {HINT}"
        for record, shape in want["records"].items():
            got = have["records"].get(record)
            assert got is not None, f"part {name}: record {record} left the part: {HINT}"
            assert got["v"] == shape["v"], f"part {name}: record {record} changed its V: {HINT}"
            assert got["schema"] == shape["schema"], f"part {name}: record {record} changed its fields, V stayed {shape['v']}: bump V"
        assert set(have["records"]) == set(want["records"]), f"part {name}: records added: {HINT}"
