"""`decide.decide` only chooses; `remember` and `apply_profile` are the writes, and `decision` runs them in the order next and run use."""

import contextlib
import copy
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import CFG, T, argparse_ns, lanes

from delegate.app import decide as dec
from delegate.app import env


def fleet():
    """The fleet, the clock and `how` (which would ask git about the folder) as fakes."""
    stack = contextlib.ExitStack()
    stack.enter_context(support.fleet_patches(lanes()))
    stack.enter_context(mock.patch.object(env, "now", return_value=T))
    stack.enter_context(mock.patch.object(dec, "how", return_value={"kind": "codex", "cwd": "/w"}))
    return stack


def test_decide_writes_neither_state_nor_profile():
    a = argparse_ns("worker")
    with fleet(), mock.patch.object(env, "update_state") as state, mock.patch.object(dec, "apply_profile") as profile:
        decided = dec.decide(a, copy.deepcopy(CFG))
    state.assert_not_called()
    profile.assert_not_called()
    assert decided.d["action"] == "run"


def test_decision_is_decide_then_remember_and_returns_the_same_tuple():
    a = argparse_ns("worker")
    with fleet():
        decided = dec.decide(a, copy.deepcopy(CFG))
        d, ls, warnings, t = dec.decision(a, copy.deepcopy(CFG))
    assert (d["lane"], d["model"], warnings, t) == (decided.d["lane"], decided.d["model"], decided.warnings, decided.t)
    assert set(ls) == set(decided.lanes)


def test_only_apply_writes_the_profile_and_remember_writes_the_dwell():
    a = argparse_ns("worker")
    with fleet(), mock.patch.object(dec, "apply_profile") as profile, mock.patch.object(dec, "remember") as remember:
        dec.decision(a, copy.deepcopy(CFG))
        profile.assert_not_called()
        dec.decision(a, copy.deepcopy(CFG), apply=True)
    profile.assert_called_once()
    assert remember.call_count == 2
