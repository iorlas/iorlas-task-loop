"""tlslots.machine runs on the host it is given and on nothing else: a fake SlotsHost answers every machine question, and the module
names no adapter of the shell."""
import ast
from pathlib import Path

import pytest

from support.dashlogs import bead
from support.fakes import FakeBeadStore
from support.who import who
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.ids import BeadId
from tlslots import machine
from tlslots.env import DEFAULT_PRIO
from tlslots.host import SlotsHost

HOST = "fakehost"
PACKAGE = Path(machine.__file__).parent


def fake_host(store, *, peek=None):
    def refused(*args, **kwargs):
        raise AssertionError("the test did not expect this machine question")

    return SlotsHost(
        bd=lambda actor, repo: store, peek=peek or (lambda s, bead_id: s.show(bead_id)), repo_root=lambda: "/repo",
        hostname=lambda: HOST, os_lock=refused, event=refused, tickets=refused, now=lambda: 1.0, fx=refused)


def slot(name, host=HOST, status="open"):
    return bead(f"s-{name}-{host}", f"slot {host} {name}", status, labels=["slot"])


def test_the_slot_beads_are_those_of_the_hosts_own_name():
    store = FakeBeadStore().put(slot("s1")).put(slot("s2", host="elsewhere"))
    got = machine.slot_beads(fake_host(store), "/repo", who())
    assert [b.title for b in got] == [f"slot {HOST} s1"]


def test_a_named_slot_is_found_among_them_and_a_missing_one_is_none():
    store = FakeBeadStore().put(slot("s1"))
    h = fake_host(store)
    assert machine.slot_bead(h, "/repo", "s1", who()).title == f"slot {HOST} s1"
    assert machine.slot_bead(h, "/repo", "s9", who()) is None


def test_a_bead_priority_is_the_one_the_host_reads_and_a_missing_bd_waits_as_the_default():
    store = FakeBeadStore().put(bead("b-1", priority=0))
    assert machine.bead_priority(fake_host(store), "/repo", BeadId("b-1"), who()) == 0

    def no_bd(*args):
        raise BdCommandFailure("tl: bd is not on PATH")

    assert machine.bead_priority(fake_host(store, peek=no_bd), "/repo", BeadId("b-1"), who()) == DEFAULT_PRIO


def test_the_live_actors_are_those_holding_an_unexpired_lease():
    store = FakeBeadStore()
    store.put(bead("b-1", status="in_progress", assignee="tl-a", lease_expires_at="9999-01-01T00:00:00"))
    store.put(bead("b-2", status="in_progress", assignee="tl-b", lease_expires_at="2000-01-01T00:00:00"))
    assert machine.live_actors(fake_host(store), "/repo", who()) == {"tl-a"}


@pytest.mark.parametrize("name", ["machine.py", "host.py"])
def test_the_machine_half_imports_nothing_of_the_shell(name):
    tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not {r for r in roots if r.startswith("taskloop")}
