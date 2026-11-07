"""Admission checks use only in-memory beads, diffs, and queue ports."""
from types import SimpleNamespace

import pytest

from taskloop.app.land.cmds import Stop
from taskloop.app.land.queue_enqueue import enqueue
from taskloop.contracts.bead import Bead, Dep
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.contracts.ids import BeadId


def host_for(records=(), paths=None):
    records = {record.id: record for record in records}
    paths = paths or {}
    calls, notes = [], []

    def show(bead):
        calls.append(bead)
        return records.get(bead)

    host = SimpleNamespace(
        beads=SimpleNamespace(show=show), jobs=4, repo="repo",
        trees=SimpleNamespace(main_ref="origin/main"),
        cmds=SimpleNamespace(log=SimpleNamespace(note=notes.append)),
        git=SimpleNamespace(
            merge_base=lambda repo, main, oid: "base-" + oid,
            diff_entries=lambda repo, base, oid: [DiffEntry(status="M", path=p) for p in paths.get(oid, [])],
        ),
    )
    return host, calls, notes


def bead(name, parents=()):
    return Bead(id=BeadId(name), title=name, status="open", dependencies=list(parents))


@pytest.mark.parametrize("records,order", [
    ([], ["child"]),
    ([bead("child", [Dep(id="parent", type="blocks", status="closed")])], ["child"]),
    ([bead("child", [Dep(id="parent", type="blocks")])], ["parent", "child"]),
    ([bead("child", [Dep(id="parent", type="related")])], ["child"]),
], ids=["no dependencies", "closed parent", "earlier parent", "other edge type"])
def test_ready_dependencies(records, order):
    host, calls, _notes = host_for(records)
    assert enqueue(host, [(b, b) for b in order], dict(zip(order, order, strict=True))) == 4
    assert len(calls) == len(set(calls))


@pytest.mark.parametrize("records,why", [
    ([bead("child", [Dep(id="parent", type="blocks")])],
     "queue: child waits for parent (not merged to main)"),
    ([bead("child", [Dep(id="parent", type="blocks")]),
      bead("parent", [Dep(id="child", type="blocks")])],
     "queue: dependency cycle child -> parent -> child"),
], ids=["open parent", "cycle"])
def test_refuses_dependencies(records, why):
    host, _calls, _notes = host_for(records)
    with pytest.raises(Stop) as stop:
        enqueue(host, [("child", "head")], {"child": "child"})
    assert stop.value.why == why


@pytest.mark.parametrize("paths,expected", [
    ({"a": ["src/land"], "b": ["src/land/file.py"]}, 1),
    ({"a": ["src/land/a.py"], "b": ["src/other/b.py"]}, 4),
], ids=["overlap", "disjoint"])
def test_path_overlap_selects_concurrency(paths, expected):
    host, _calls, notes = host_for(paths=paths)
    assert enqueue(host, [("a", "a"), ("b", "b")], {}) == expected
    assert notes == (["b waits for a: touched paths overlap"] if expected == 1 else [])


def test_item_without_bead_is_ignored():
    host, calls, _notes = host_for()
    assert enqueue(host, [("ordinary", "head")], {"ordinary": ""}) == 4
    assert calls == []


def test_walk_is_bounded_and_fetches_each_bead_once():
    records = [bead(str(i), [Dep(id=str(i + 1), type="blocks", status="closed")]) for i in range(70)]
    host, calls, _notes = host_for(records)
    assert enqueue(host, [("root", "head")], {"root": "0"}) == 4
    assert calls == [str(i) for i in range(64)]

