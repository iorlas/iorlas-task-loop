"""LandState: the land's unsaved state starts empty and is one object per run (docs/design/b-land.md, slice 2)."""
from taskloop.app.land.state import LandState


def test_starts_empty() -> None:
    s = LandState()
    assert (s.gate_log, s.salvage_tail, s.rebase_orig, s.rebase_pre, s.salvaged, s.remote_oid) == (None, "", "", [], False, "")


def test_two_states_share_nothing() -> None:
    a, b = LandState(), LandState()
    a.rebase_pre.append("h")
    assert b.rebase_pre == []
