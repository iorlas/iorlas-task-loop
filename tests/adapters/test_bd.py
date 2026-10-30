"""adapters/bd.py: the shared Beads contract on the fake and on real bd (a throwaway database; skipped without bd), the golden
bd 1.3.1 outputs through the real adapter's parser (the process replaced by the captured text), and logic tests on the fake."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from ports.beads_contract import BeadsContract
from support.fake_beads import FakeBeads
from support.tags import contract, domain

from taskloop.adapters import bd
from taskloop.adapters.bd import BdRun, BdStore, create_argv, update_argv
from taskloop.contracts.bead import BdError
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead

GOLD = Path(__file__).parent / "golden" / "bd_1_3_1"


def gold(name: str) -> str:
    return (GOLD / name).read_text(encoding="utf-8")


@contract
class FakeBeadsContract(BeadsContract, unittest.TestCase):
    def make(self) -> FakeBeads:
        return FakeBeads(actor=self.ACTOR)


@contract
class RealBdContract(BeadsContract, unittest.TestCase):
    """One `bd init` (13 s) for the class; every test makes its own beads and lists only what it created, so the
    database is shared. Skipped when bd is not installed or cannot init."""

    root: str = ""
    why_not: str = ""  # a skip is per test, never in setUpClass: unittest does not count the tests of a class skipped there,
    # and the release gate fails a run whose count differs from the planned one (the container has no bd)

    @classmethod
    def setUpClass(cls) -> None:
        exe = shutil.which("bd")
        if not exe:
            cls.why_not = "bd is not installed"
            return
        cls.root = tempfile.mkdtemp(prefix="ports-bd-")
        subprocess.run(["git", "init", "-q"], cwd=cls.root, check=True)
        r = subprocess.run([exe, "init", "--quiet", "--prefix", "pt"], cwd=cls.root, capture_output=True, text=True,
                           env=dict(os.environ, HOME=cls.root), check=False)
        if r.returncode != 0:
            shutil.rmtree(cls.root, ignore_errors=True)
            cls.root = ""
            cls.why_not = f"bd init failed: {r.stderr[-200:]}"

    def setUp(self) -> None:
        if self.why_not:
            self.skipTest(self.why_not)
        super().setUp()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def make(self) -> BdStore:
        return BdStore(actor=self.ACTOR, cwd=self.root)


@contract
class GoldenBd(unittest.TestCase):
    """bd 1.3.1's real output through the real adapter, with the process replaced by the captured text."""

    def beads(self, **by_cmd: BdRun) -> BdStore:
        calls = []

        def run(argv: list[str], cwd: str | None) -> BdRun:
            calls.append(argv)
            return by_cmd[argv[3]]
        b = BdStore("x", run=run)
        b.calls = calls  # type: ignore[attr-defined]
        return b

    def test_show_of_a_claimed_bead_with_metadata(self) -> None:
        b = self.beads(show=BdRun(0, gold("show_in_progress.json"), "")).show("t-gold")
        assert b is not None
        self.assertEqual((b.status, b.assignee, b.metadata), ("in_progress", "x", {"slot": "s1", "held_bead": "t-dhc"}))
        self.assertTrue(b.lease_expires_at)

    def test_a_fenced_close_guards_with_a_same_value_update_then_closes_with_the_reason(self) -> None:
        b = self.beads(update=BdRun(0, "", ""), close=BdRun(0, "", ""))
        b.close("t-1", "landed", if_assignee="loop")
        self.assertEqual([c[3:] for c in b.calls], [  # type: ignore[attr-defined]
            ["update", "t-1", "--if-assignee", "loop", "--assignee", "loop", "--json"], ["close", "t-1", "--reason", "landed", "--json"]])

    def test_a_fenced_close_on_a_moved_bead_never_closes(self) -> None:
        b = self.beads(update=BdRun(13, "", "assignee mismatch"))
        with self.assertRaises(BdFailure):
            b.close("t-1", "landed", if_assignee="loop")
        self.assertEqual([c[3] for c in b.calls], ["update"])  # type: ignore[attr-defined]

    def test_show_missing_is_none(self) -> None:
        self.assertIsNone(self.beads(show=BdRun(1, gold("show_missing.out"), gold("show_missing.err"))).show("nope"))

    def test_comments(self) -> None:
        got = self.beads(comments=BdRun(0, gold("comments.json"), "")).comments("t-eis")
        self.assertEqual([(c.author, c.text) for c in got], [("x", "hi there")])

    def test_list_and_ready(self) -> None:
        got = self.beads(list=BdRun(0, gold("list_open_and_in_progress.json"), ""), ready=BdRun(0, gold("ready.json"), ""))
        self.assertEqual([b.id for b in got.find(BeadQuery())], ["t-dhc"])
        self.assertEqual([b.id for b in got.ready()], ["t-dhc"])

    def test_closed_list_reads_status_and_sorted_labels(self) -> None:
        got = self.beads(list=BdRun(0, gold("list_closed.json"), "")).find(BeadQuery(status="closed"))
        self.assertEqual([(b.id, b.status, b.labels) for b in got], [("t-eis", "closed", ["a", "slot"])])

    def test_create_answer_gives_the_id(self) -> None:
        self.assertEqual(self.beads(create=BdRun(0, gold("create.json"), "")).create(NewBead(title="gold")), "t-gold")

    def test_a_closed_bead_claim_is_refused_with_no_exception(self) -> None:
        self.assertFalse(self.beads(update=BdRun(1, gold("claim_closed.out"), gold("claim_closed.err"))).claim("t-eis"))

    def test_error_kinds(self) -> None:
        self.assertEqual(bd.error_of(gold("claim_closed.err"), "").kind, "not_claimable")
        self.assertEqual(bd.error_of(gold("show_missing.err"), gold("show_missing.out")).kind, "not_found")
        lint = bd.error_of(gold("create_lint_refused.err"), "")
        self.assertEqual((lint.kind, lint.missing_sections), ("lint", ["Acceptance Criteria", "Touches"]))

    def test_a_refused_create_raises_with_the_sections(self) -> None:
        b = self.beads(create=BdRun(1, "", gold("create_lint_refused.err")))
        with self.assertRaises(BdFailure) as cm:
            b.create(NewBead(title="t"))
        self.assertEqual(cm.exception.error.missing_sections, ["Acceptance Criteria", "Touches"])

    def test_argv(self) -> None:
        self.assertEqual(create_argv(NewBead(title="T", labels=["a", "b"], priority=1, parent="p-1", no_inherit_labels=True)),
                         ["create", "T", "--type", "task", "--parent", "p-1", "--priority", "1", "--labels", "a,b",
                          "--no-inherit-labels"])
        self.assertEqual(update_argv("b-1", BeadPatch(status="open", assignee="", set_metadata={"k": "v"}, unset_metadata=["z"])),
                         ["update", "b-1", "--status", "open", "--assignee", "", "--set-metadata", "k=v", "--unset-metadata", "z"])

    def test_dependencies_read_the_same_from_show_and_list(self) -> None:
        shown = self.beads(show=BdRun(0, gold("show_blocked_by.json"), "")).show("zz-kgz")
        listed = self.beads(list=BdRun(0, gold("list_with_parent_dep.json"), "")).find(BeadQuery(label="a"))[0]
        assert shown is not None
        self.assertEqual([(d.id, d.type, d.title, d.status) for d in shown.dependencies], [("zz-6to.1", "blocks", "Child", "in_progress")])
        self.assertEqual([(d.id, d.type) for d in listed.dependencies], [("zz-6to", "parent-child")])
        self.assertEqual(listed.parent, "zz-6to")

    def test_every_call_carries_the_actor_and_json(self) -> None:
        store = self.beads(show=BdRun(0, gold("show_open.json"), ""), comments=BdRun(0, "[]", ""), update=BdRun(0, "[]", ""))
        store.show("x")
        store.comments("x")
        store.claim("x")
        store.update("x", BeadPatch(status="open"))
        for argv in store.calls:  # type: ignore[attr-defined]
            self.assertEqual((argv[1], argv[2], argv[-1]), ("--actor", "x", "--json"), argv)

    def test_error_text_comes_from_bds_json_error_key(self) -> None:
        self.assertEqual(bd.error_of(gold("claim_taken.err"), gold("claim_taken.out")).kind, "not_claimable")
        self.assertEqual(bd.error_of("", gold("show_missing_json.out")).kind, "not_found")
        self.assertEqual(bd.error_of(gold("provenance_refused.err"), gold("provenance_refused.out")).kind, "other")
        self.assertIn("unknown kind", bd.error_of("", gold("provenance_refused.out")).text)

    def test_reclaim_and_provenance_argv(self) -> None:
        store = self.beads(reclaim=BdRun(0, gold("reclaim.json"), ""), provenance=BdRun(0, "{}", ""))
        store.reclaim("15m", ["a", "b"])
        store.provenance("b-1", "k", "tl", at="2026-01-01T00:00:00Z")
        self.assertEqual(store.calls[0][3:], ["reclaim", "--older-than", "15m", "--assignee", "a", "--assignee", "b", "--json"])  # type: ignore[attr-defined]
        self.assertEqual(store.calls[1][3:7], ["provenance", "record", "--issue", "b-1"])  # type: ignore[attr-defined]

    REJECTED = ("error: failed to push some refs to 'git+https://x/y.git'\nhint: Updates were rejected because the tip of your "
                "current branch is behind")

    def test_a_dolt_push_bd_rejects_with_exit_0_fails(self) -> None:
        store = self.beads(sync=BdRun(0, "", self.REJECTED), dolt=BdRun(0, "", self.REJECTED))
        self.assertEqual(store.dolt_push().code, 1)
        self.assertIn("Updates were rejected", store.dolt_push().text)
        self.assertEqual(store.passthrough(["dolt", "push"]).code, 1)

    def test_a_sync_conflict_keeps_bds_words_and_code(self) -> None:
        words = "merge conflict in tables: child_counters, issues"
        self.assertEqual(self.beads(sync=BdRun(2, "", words)).dolt_push(), DoltPush(2, words))

    def test_a_synced_push_is_ok_and_runs_bd_sync(self) -> None:
        store = self.beads(sync=BdRun(0, "", "Pushing to Dolt remote..."), dolt=BdRun(0, "", "Pushing to Dolt remote..."))
        self.assertEqual(store.dolt_push().code, 0)
        self.assertEqual(store.calls[0][3:], ["sync", "--no-adopt", "--json"])  # type: ignore[attr-defined]
        self.assertEqual(store.passthrough(["dolt", "push"]).code, 0)

    def test_every_golden_file_is_json_or_text(self) -> None:
        for f in GOLD.glob("*.json"):
            json.loads(f.read_text(encoding="utf-8"))


@domain
class FakeBeadsLogic(unittest.TestCase):
    def test_a_scripted_create_refusal_then_success(self) -> None:
        beads = FakeBeads()
        beads.refuse_create.append(BdError(kind="lint", missing_sections=["Touches"]))
        with self.assertRaises(BdFailure) as cm:
            beads.create(NewBead(title="t"))
        self.assertEqual(cm.exception.error.missing_sections, ["Touches"])
        self.assertEqual(beads.create(NewBead(title="t")), "fk-1")

    def test_a_dependency_keeps_a_bead_off_ready_until_it_closes(self) -> None:
        beads = FakeBeads()
        first = beads.create(NewBead(title="first"))
        second = beads.create(NewBead(title="second", deps=[first]))
        self.assertEqual([b.id for b in beads.ready()], [first])
        beads.close(first, "done")
        self.assertEqual([b.id for b in beads.ready()], [second])


if __name__ == "__main__":
    unittest.main()
