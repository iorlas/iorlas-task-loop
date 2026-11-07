"""Ownership records of tl's worktrees as kv rows: written and read back, an unknown key refused."""
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
    docs.of("a-1").delete()
    assert docs.of("a-1").get() is None and docs.keys() == []


def test_an_unknown_key_is_refused_and_repos_do_not_mix(repo):
    cfg = homes.cfg()
    docs = WorktreeDocs(cfg, repo)
    docs.of("a-1").write(owned())
    with docs.of("a-1").rows.transaction() as con:
        body = dict(wire.dump(owned()), future=1)
        con.execute("UPDATE kv SET v=? WHERE k=?", (json.dumps(body), docs.of("a-1").k))
    assert docs.of("a-1").get() is None
    assert WorktreeDocs(cfg, repo + "x").keys() == []
