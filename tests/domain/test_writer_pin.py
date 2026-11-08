"""A bead's writer label is an opaque delegate preference."""
import pytest

from taskloop.app.workers import writer_pin
from taskloop.domain.accounts import pin


@pytest.mark.parametrize("labels,expected", [([], ""), (["writer-family:"], ""),
    (["writer-family:codex-ish"], "codex-ish"), (["writer-family:xai", "writer-family:claude"], "claude")])
def test_prefer_of(labels, expected):
    assert pin.prefer_of(labels) == expected


@pytest.mark.parametrize("role", ["planner", "reviewer", "reviewer_fast"])
def test_only_worker_carries_prefer(role):
    labels = ["writer-family:codex-ish"]
    assert writer_pin.prefer(labels, "worker") == "codex-ish"
    assert writer_pin.prefer(labels, role) == ""


def test_stop_words_name_prefer_and_label():
    why = pin.stop_why("write", "codex-ish", "only_family_unready", "account out")
    assert "codex-ish" in why
    assert "writer-family:<f>" in why
    assert "no other family is used" in why


def test_unenforced_words():
    why = pin.unenforced_why("write", "cannot deny", "use advisory")
    assert "cannot deny" in why
    assert "use advisory" in why
