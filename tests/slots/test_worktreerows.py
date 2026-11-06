"""Ownership records of tl's worktrees as kv rows: written and read back, an older tl's file adopted, a newer writer's keys read past."""
import json
import uuid

import pytest
import support.paths  # noqa: F401
from support import homes
from support.narrow import must

from taskloop.contracts import wire
from taskloop.contracts.worktreerows import WorktreeDocs
from taskloop.contracts.worktrees import Owned


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
    assert not homes.cfg().worktree_record(repo, "a-1").exists()
    docs.of("a-1").delete()
    assert docs.of("a-1").get() is None and docs.keys() == []


def test_an_older_tls_file_is_listed_read_and_adopted_into_a_row(repo):
    cfg = homes.cfg()
    path = cfg.worktree_record(repo, "old-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wire.dump(owned("old"))))
    docs = WorktreeDocs(cfg, repo)
    assert docs.keys() == ["old-1"]
    assert must(docs.of("old-1").get()).bead == "old"
    assert not path.exists() and docs.keys() == ["old-1"]  # now a row


def test_a_newer_writers_extra_keys_are_read_past_and_repos_do_not_mix(repo):
    cfg = homes.cfg()
    docs = WorktreeDocs(cfg, repo)
    docs.of("a-1").write(owned())
    with docs.of("a-1").rows.transaction() as con:
        body = dict(wire.dump(owned()), future=1)
        con.execute("UPDATE kv SET v=? WHERE k=?", (json.dumps(body), docs.of("a-1").k))
    assert must(docs.of("a-1").get()).kind == "slot"
    assert WorktreeDocs(cfg, repo + "x").keys() == []
