"""Ownership records of tl's worktrees as worktree_doc rows: written and read back, an unknown key refused."""
import json
import uuid

import pytest
import support.paths  # noqa: F401
from support import homes
from support.narrow import must

from tlkernel import wire
from tlkernel.worktreerows import WorktreeDocs
from tlkernel.worktrees import Owned


@pytest.fixture
def repo():
    """A repo key of its own: the config dir is shared by the tests of a process."""
    return f"repo-{uuid.uuid4().hex[:8]}"


def owned(bead="b-1"):
    return Owned(path="/wt/a", repo="/r", kind="slot", run="tl-x", bead=bead, host="h", created=5.0)


def test_a_record_is_written_read_listed_and_deleted(repo):
    docs = WorktreeDocs(homes.cfg(), repo)
    docs.of("a-1").write(owned())
    assert must(docs.of("a-1").get()).bead == "b-1" and docs.keys() == ["a-1"]
    docs.of("a-1").delete()
    assert docs.of("a-1").get() is None and docs.keys() == []


def test_an_unknown_key_is_refused_and_repos_do_not_mix(repo):
    cfg = homes.cfg()
    docs = WorktreeDocs(cfg, repo)
    docs.of("a-1").write(owned())
    with docs.of("a-1").rows.transaction() as con:
        body = dict(wire.dump(owned()), future=1)
        con.execute("UPDATE worktree_doc SET v=? WHERE k=?", (json.dumps(body), docs.of("a-1").k))
    assert docs.of("a-1").get() is None
    assert WorktreeDocs(cfg, repo + "x").keys() == []


def test_ownership_lives_in_worktree_doc_only(repo):
    doc = WorktreeDocs(homes.cfg(), repo).of("a-1")
    doc.write(owned())
    assert doc.rows.select("SELECT k FROM worktree_doc WHERE k=?", (doc.k,)) == [(doc.k,)]
    assert doc.rows.select("SELECT k FROM kv WHERE k=?", (doc.k,)) == []
    assert doc.get() == owned()
