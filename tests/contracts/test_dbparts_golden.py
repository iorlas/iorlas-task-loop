"""The golden fingerprints: a change to a part's tables or records cannot reach main without a version bump of the part."""
import json
from pathlib import Path

from taskloop.app.parts import STAGE_PARTS
from tlkernel import dbparts

GOLDEN = Path(__file__).parent / "golden" / "parts.json"
HINT = "bump the part's version, add its step, then run `uv run python dev/part_golden.py`"


def test_every_part_matches_its_golden_fingerprint():
    golden = json.loads(GOLDEN.read_text())
    now = json.loads(json.dumps(dbparts.golden(STAGE_PARTS)))
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


def test_a_version_never_changes_what_it_stored():
    """The fingerprints a db stores for a part's version are committed: a change to the part at the same version fails here."""
    golden = json.loads(GOLDEN.read_text())
    now = json.loads(json.dumps(dbparts.golden(STAGE_PARTS)))
    for name, part in now.items():
        seen = golden[name]["history"].get(str(part["version"]))
        assert seen == part["history"][str(part["version"])], f"part {name} v{part['version']} changed without a version bump: {HINT}"
