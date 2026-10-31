"""The close guard (app/wire/closeguard.py): a task, feature or bug bead with an engine run or a task branch is closed only with a land on
record or a typed reason; a manual sha counts only as an ancestor of the base. `tl close`, `tl bd close` and the release go through it."""
import contextlib
import io
import time
import unittest
from unittest import mock

import support.paths  # noqa: F401
from support import homes
from support.who import who

# isort: split
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit

from taskloop.app.track import verbs
from taskloop.app.wire import closeguard
from taskloop.contracts.bead import Bead
from taskloop.contracts.enums import Outcome
from taskloop.contracts.gitfacts import Ref
from taskloop.contracts.ids import BeadId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.stores import TraceStore

SHA = "a" * 40


class Git(ScriptedGit):
    """Branches and ancestry from a table."""

    def __init__(self, branches: tuple[str, ...] = (), on_base: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.branches, self.on_base = branches, on_base

    def for_each_ref(self, d, *prefixes):
        return [Ref(name=b, oid=SHA) for b in self.branches if any(b.startswith(p) for p in prefixes)]

    def is_ancestor(self, d, a, b):
        return a in self.on_base

    def rev_parse(self, d, rev):
        return rev.removesuffix("^{commit}")

    def remote_url(self, d, remote):
        return "git@x:y/z.git"


class Guarded(unittest.TestCase):
    n = 0

    def setUp(self):
        Guarded.n += 1
        self.bead = BeadId(f"cg-{Guarded.n}")
        self.bd = FakeBeads(actor="tl-me")
        patch = mock.patch.object(closeguard.wslots, "load_cfg", return_value=mock.Mock(base="origin/main"))
        patch.start()
        self.addCleanup(patch.stop)

    def add(self, kind="task"):
        self.bd.beads[self.bead] = Bead(id=self.bead, title="t", status="open", issue_type=kind)

    def ask(self, reason, git=None):
        return closeguard.refusal(who(), self.bd, git or Git(), "/r", self.bead, reason)

    def run_of_bead(self):
        RunLocator(homes.cfg()).create("/r", self.bead, time.time())

    def landed(self):
        TraceStore(homes.cfg())  # the store exists; the row comes from record_land
        self.assertEqual(closeguard.record_land(who(), self.bd, Git(on_base=(SHA,)), "/r", "origin/main", self.bead, SHA, "t"), 0)

    def test_a_run_and_no_land_is_refused_and_names_the_fix(self):
        self.add()
        self.run_of_bead()
        why = self.ask("done")
        self.assertIn("no land on record", why)
        self.assertIn(f"tl land {self.bead} --sha SHA", why)
        self.assertIn(f"tl bd close {self.bead} --reason 'manual-landed-with-sha:<sha>", why)

    def test_a_task_branch_alone_is_refused_local_or_origin(self):
        self.add("bug")
        for ref in (f"refs/heads/task/{self.bead}", f"refs/remotes/origin/task/{self.bead}"):
            self.assertIn("no land", self.ask("done", Git(branches=(ref,))))

    def test_no_run_and_no_branch_closes_freely(self):
        self.add()
        self.assertEqual(self.ask("done"), "")

    def test_an_epic_and_other_types_close_freely_even_with_a_run(self):
        self.add("epic")
        self.run_of_bead()
        self.assertEqual(self.ask("done"), "")
        self.add("chore")
        self.assertEqual(self.ask("done"), "")

    def test_each_typed_reason_closes(self):
        self.add()
        self.run_of_bead()
        for r in ("duplicate of x-1", "wontfix: not needed", "superseded by x-2", "epic"):
            self.assertEqual(self.ask(r), "", r)

    def test_a_land_on_record_closes(self):
        self.add()
        self.run_of_bead()
        self.landed()
        self.assertEqual(self.ask("done"), "")

    def test_a_manual_sha_is_accepted_only_as_an_ancestor_and_is_recorded_as_the_land(self):
        self.add()
        self.run_of_bead()
        why = self.ask(f"manual-landed-with-sha:{SHA} hand merge", Git(on_base=()))
        self.assertIn("not an ancestor of origin/main", why)
        self.assertFalse(closeguard.has_land(who(), self.bead))
        self.assertEqual(self.ask(f"manual-landed-with-sha:{SHA} hand merge", Git(on_base=(SHA,))), "")
        rows = [i.rec for i in TraceStore(homes.cfg()).read_from(0).items if i.rec.bead == self.bead]
        self.assertEqual([(r.outcome, r.sha) for r in rows], [(Outcome.LANDED, SHA)])
        self.assertEqual(self.ask("done"), "")  # the land is on record now

    def test_close_as_refuses_before_bd_and_the_engine_guard_passes(self):
        self.add()
        self.run_of_bead()
        self.bd.beads[self.bead] = self.bd.beads[self.bead].replace(assignee="tl-me", status="in_progress")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = verbs.close(who(), self.bead, self.bd, closeguard.guard_for(who(), self.bd, Git(), "/r"), "done")
        self.assertEqual(rc, 1)
        self.assertIn("no land on record", err.getvalue())
        self.assertEqual(self.bd.beads[self.bead].status, "in_progress")
        self.assertEqual(verbs.close(who(), self.bead, self.bd, closeguard.ENGINE, "merged"), 0)
        self.assertEqual(self.bd.beads[self.bead].status, "closed")

    def test_tl_bd_close_is_guarded_by_id_and_reason_in_any_spelling(self):
        self.add()
        self.run_of_bead()
        self.assertEqual(verbs.bd_close_args(["close", str(self.bead), "-r", "duplicate x"]), ([str(self.bead)], "duplicate x"))
        self.assertEqual(verbs.bd_close_args(["done", "--reason=wontfix", str(self.bead), "--session", "s"]), ([str(self.bead)], "wontfix"))
        guard = closeguard.guard_for(who(), self.bd, Git(), "/r")
        store = mock.Mock()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(verbs.passthrough(store, ["close", str(self.bead), "--reason", "done"], guard), 1)
        store.passthrough.assert_not_called()
        self.assertIn("no land on record", err.getvalue())
        store.passthrough.return_value = mock.Mock(out="", err="", code=0)
        self.assertEqual(verbs.passthrough(store, ["close", str(self.bead), "--reason", "wontfix"], guard), 0)
        self.assertEqual(verbs.passthrough(store, ["list"], guard), 0)

    def test_a_release_records_its_push_as_the_land_then_closes(self):
        self.add()
        self.run_of_bead()
        git = Git(on_base=(SHA,))
        git.rev_parse = lambda d, rev: SHA  # type: ignore[method-assign]
        self.assertEqual(closeguard.close_released(who(), self.bd, git, "/clone", self.bead, "released 1.2.3", "1.2.3"), "")
        self.assertEqual(self.bd.beads[self.bead].status, "closed")
        self.assertTrue(closeguard.has_land(who(), self.bead))


if __name__ == "__main__":
    unittest.main()
