"""The quarantine list (tests/quarantine.txt) may only shrink: judged on the change, against the merge base with origin/main.
A deliberate rise is a commit-message line `Ratchet-allow: quarantine +N <reason in words>` (tests/rules/ratchet_change.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import flakes  # noqa: E402

from rules import ratchet_change as rc  # noqa: E402

REL = "tests/quarantine.txt"


def ids(text):
    return [s for s in (line.strip() for line in text.splitlines()) if s and not s.startswith("#")]


def test_the_quarantine_list_did_not_grow_in_this_change():
    base = rc.merge_base(ROOT)
    if base is None:
        pytest.skip("no origin/main: nothing to compare with")
    old = rc.git(ROOT, "show", f"{base}:{REL}")
    before = len(ids(old.stdout)) if old.returncode == 0 else 0
    after = len(flakes.quarantined(ROOT / REL))
    assert after - before <= rc.allowed(ROOT, base, "quarantine"), f"{REL} grew from {before} to {after}: the list only shrinks"
