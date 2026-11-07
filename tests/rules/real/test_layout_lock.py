"""Judge this change's layout once Denis enables the lock."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rules import layout_lock
from rules.gate_rules import ROOT


def test_this_change_preserves_layout():
    if not layout_lock.ENABLED:
        pytest.skip("layout lock disabled until Denis freezes the codebase layout")
    bad = layout_lock.problems(ROOT)
    if bad is None:
        pytest.skip("no origin/main to compare with")
    assert bad == [], "\n".join(bad)
