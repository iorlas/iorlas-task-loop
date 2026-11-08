"""Slot claim outcomes and the run-task ownership hand-over."""
import contextlib
import threading
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from tlkernel.bead import Bead
from tlkernel.config import SlotsConfig
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.run import RUN_SLOT, Reexec

from tlslots import machine
from tlslots.testing import FakeSlotGit, FakeSlotsHost


@pytest.fixture
def rig(monkeypatch):
    host = FakeSlotsHost()
    return host, {"spawner": Mock(), "git": FakeSlotGit(), "who": Identity(actor="test", home="/config")}


def test_named_refused(rig, monkeypatch):
    host, kw = rig
    monkeypatch.setattr(machine, "profile_slots", lambda repo: SlotsConfig())
    monkeypatch.setattr(machine, "take_named_slot", lambda *a, **kw: (None, "held by another run"))
    got = machine.named(host.host, "/repo", "s1", None, False, "run-task b-1", host.store, env=Env(), **kw)
    assert got == machine.Taken(refused="held by another run")


def test_handed_slot_is_kept(rig, monkeypatch):
    host, kw = rig
    def no_take(*a, **kw):
        pytest.fail("a handed slot must not be taken again")
    monkeypatch.setattr(machine, "take_named_slot", no_take)
    env = Env().with_(EnvVar.TL_REEXEC, Reexec(run="r", bead="b-1", frm="v1", owned="s1").text())
    assert machine.handed_slot("s1", env)
    got = machine.named(host.host, "/repo", "s1", BeadId("sl-1"), True, "run-task b-1", host.store, env=env, **kw)
    assert got == machine.Taken(BeadId("sl-1"))


@pytest.mark.parametrize("stopped", [False, True])
def test_any_without_slot(rig, monkeypatch, stopped):
    host, kw = rig
    monkeypatch.setattr(machine, "uninitialised", lambda *a, **kw: "")
    monkeypatch.setattr(machine, "wait_slot", lambda *a, **kw: None)
    halt = threading.Event()
    if stopped:
        halt.set()
    got = machine.any_slot(host.host, "/repo", SlotsConfig(), BeadId("b-1"), False, halt, Mock(), host.store, **kw)
    assert got == (machine.Stopped() if stopped else machine.Refused("no free slot (tl slot list); --wait waits in line for one"))


def test_any_uninitialised(rig, monkeypatch):
    host, kw = rig
    monkeypatch.setattr(machine, "uninitialised", lambda *a, **kw: "no slots on fakehost: run `tl slot init` (2 in the profile)")
    got = machine.any_slot(host.host, "/repo", SlotsConfig(), BeadId("b-1"), True, threading.Event(), Mock(), host.store, **kw)
    assert got == machine.Refused("no slots on fakehost: run `tl slot init` (2 in the profile)")


def test_any_claim_reads_generation_and_notifies_once(rig, monkeypatch):
    host, kw = rig
    host.store.put(Bead(id=BeadId("sl-1"), title="slot", status="open", metadata={"held_gen": 7}))
    monkeypatch.setattr(machine, "uninitialised", lambda *a, **kw: "")
    def wait(*a, on_wait, prio, **kw):
        assert prio == 2
        on_wait(3)
        host.t += 1
        on_wait(0)
        return "s1", "/repo/s1", BeadId("sl-1")
    monkeypatch.setattr(machine, "wait_slot", wait)
    said = []
    got = machine.any_slot(host.host, "/repo", SlotsConfig(), BeadId("b-1"), True, threading.Event(), said.append, host.store, **kw)
    assert got == machine.Claim("s1", "/repo/s1", BeadId("sl-1"), 7)
    assert said == ["no free slot (3 ahead); waiting in line"]


def test_give_back_releases_once_under_guard(rig, monkeypatch):
    host, kw = rig
    calls = []
    events = []
    @contextlib.contextmanager
    def guard():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")
    def release(*a, **kwargs):
        assert events == ["enter"]
        events.append("release")
        calls.append((a, kwargs))
    monkeypatch.setattr(machine, "release_slot", release)
    machine.give_back(host.host, "/repo", "s1", BeadId("b-1"), 7, host.store, guard=guard, **kw)
    assert events == ["enter", "release", "exit"]
    assert len(calls) == 1
    assert calls[0][1] == dict(bead=BeadId("b-1"), mine=True, store=host.store, gen=7, **kw)


def test_claimed_refusal_gives_nothing_back(rig, monkeypatch):
    host, kw = rig
    monkeypatch.setattr(machine, "named", lambda *a, **kw: machine.Taken(refused="busy"))
    release = Mock()
    monkeypatch.setattr(machine, "give_back", release)
    with machine.claimed(host.host, "/repo", "s1", None, False, "run-task b-1", host.store,
                         env=Env(), guard=contextlib.nullcontext, **kw) as claim:
        assert claim == machine.Taken(refused="busy")
    release.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_claimed_returns_fenced_slot_once_under_guard(rig, monkeypatch, raises):
    host, kw = rig
    host.store.put(Bead(id=BeadId("sl-1"), title="slot", status="open", metadata={"held_gen": 7}))
    monkeypatch.setitem(RUN_SLOT, "owned", "")
    monkeypatch.setattr(machine, "named", lambda *a, **kw: machine.Taken(BeadId("sl-1")))
    events = []
    @contextlib.contextmanager
    def guard():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")
    def release(*a, **kwargs):
        assert events == ["enter"]
        assert kwargs["gen"] == 7
        assert kwargs["bead"] == "b-1"
        events.append("release")
    monkeypatch.setattr(machine, "release_slot", release)
    with (
        pytest.raises(ValueError) if raises else contextlib.nullcontext(),
        machine.claimed(host.host, "/repo", "s1", None, False, "run-task b-1", host.store,
                        env=Env(), guard=guard, **kw) as claim,
    ):
        assert claim == machine.Taken(BeadId("sl-1"), gen=7)
        assert RUN_SLOT["owned"] == "s1"
        assert events == []
        if raises:
            raise ValueError("body")
    assert events == ["enter", "release", "exit"]


@pytest.mark.parametrize("exit_code, output", [(1, "ignored"), (0, ""), (0, "\n")])
def test_run_worktree_failure_keeps_stderr_and_tail(rig, exit_code, output):
    host, kw = rig
    err = "x" * 350 + "\n"
    kw["spawner"].run.return_value = Mock(exit=exit_code, out=output, err=err)
    with patch("sys.stderr", new_callable=StringIO) as stderr:
        got = machine.run_worktree(host.host, "", "", BeadId("b-1"), "/repo", ["python", "tl.py"],
                                   kw["spawner"], kw["who"])
    assert got == machine.Worktree("", "failed: no worktree: " + err[-300:])
    assert stderr.getvalue() == "tl: no worktree: " + err + "\n"


def test_run_worktree_uses_last_line_and_refuses_main_checkout(rig, tmp_path):
    host, kw = rig
    (tmp_path / ".git").mkdir()
    kw["spawner"].run.return_value = Mock(exit=0, out=f"setup output\n{tmp_path}\n", err="")
    with patch("sys.stderr", new_callable=StringIO) as stderr:
        got = machine.run_worktree(host.host, "", "", BeadId("b-1"), "/repo", ["python", "tl.py"],
                                   kw["spawner"], kw["who"])
    assert got == machine.Worktree("", f"failed: {tmp_path} is the main checkout")
    assert stderr.getvalue() == (
        f"tl: {tmp_path} is the main checkout; run a task in a slot or a worktree (tl slot / tl worktree start)\n")
    assert kw["spawner"].run.call_args.args == (["python", "tl.py", "worktree", "start"],)
    assert kw["spawner"].run.call_args.kwargs == {"extra": {"TASK_LOOP_ACTOR": "test"}}


def test_run_worktree_prefers_named_directory_then_slot(rig, tmp_path, monkeypatch):
    host, kw = rig
    monkeypatch.setattr(machine, "profile_slots", lambda repo: SlotsConfig())
    monkeypatch.setattr(machine, "slot_dir", lambda repo, slot, cfg: str(tmp_path / slot))
    for requested, expected in [(str(tmp_path), tmp_path), ("", tmp_path / "s1")]:
        got = machine.run_worktree(host.host, requested, "s1", BeadId("b-1"), "/repo", [],
                                   kw["spawner"], kw["who"])
        assert got == machine.Worktree(str(expected))
    kw["spawner"].run.assert_not_called()
