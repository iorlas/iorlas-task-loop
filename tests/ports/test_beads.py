"""Beads: the shared contract on the fake and on real bd (a throwaway database; skipped without bd), the golden bd 1.3.1
outputs through the real adapter's parser, and logic tests on the fake."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import support.paths  # noqa: E402,F401
from ports.beads_contract import BeadsContract  # noqa: E402
from support.tags import contract, domain  # noqa: E402
from taskloop.adapters import bd_json  # noqa: E402
from taskloop.adapters.bd_beads import BdBeads, BdRun, create_argv, update_argv  # noqa: E402
from taskloop.adapters.fake_beads import FakeBeads  # noqa: E402
from taskloop.contracts.bead import BdError  # noqa: E402
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, NewBead  # noqa: E402

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
                           env=dict(os.environ, HOME=cls.root))
        if r.returncode != 0:
            shutil.rmtree(cls.root, ignore_errors=True)
            cls.root = ""
            cls.why_not = "bd init failed: %s" % r.stderr[-200:]

    def setUp(self) -> None:
        if self.why_not:
            self.skipTest(self.why_not)
        super().setUp()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def make(self) -> BdBeads:
        return BdBeads(actor=self.ACTOR, cwd=self.root)


@contract
class GoldenBd(unittest.TestCase):
    """bd 1.3.1's real output through the real adapter, with the process replaced by the captured text."""

    def beads(self, **by_cmd: BdRun) -> BdBeads:
        calls = []

        def run(argv: list[str], cwd: str | None) -> BdRun:
            calls.append(argv)
            return by_cmd[argv[3]]
        b = BdBeads("x", run=run)
        b.calls = calls  # type: ignore[attr-defined]
        return b

    def test_show_of_a_claimed_bead_with_metadata(self) -> None:
        b = self.beads(show=BdRun(0, gold("show_in_progress.json"), "")).show("t-gold")
        assert b is not None
        self.assertEqual((b.status, b.assignee, b.metadata.held_bead, b.metadata.extra), ("in_progress", "x", "t-dhc", {"slot": "s1"}))
        self.assertTrue(b.lease_expires_at)

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
        self.assertEqual(bd_json.error_of(gold("claim_closed.err"), "").kind, "not_claimable")
        self.assertEqual(bd_json.error_of(gold("show_missing.err"), gold("show_missing.out")).kind, "not_found")
        lint = bd_json.error_of(gold("create_lint_refused.err"), "")
        self.assertEqual((lint.kind, lint.missing_sections), ("lint", ["Acceptance Criteria", "Touches"]))

    def test_a_refused_create_raises_with_the_sections(self) -> None:
        b = self.beads(create=BdRun(1, "", gold("create_lint_refused.err")))
        with self.assertRaises(BdFailure) as cm:
            b.create(NewBead(title="t"))
        self.assertEqual(cm.exception.error.missing_sections, ["Acceptance Criteria", "Touches"])

    def test_argv(self) -> None:
        self.assertEqual(create_argv(NewBead(title="T", labels=["a", "b"], priority=1, parent="p-1", no_inherit_labels=True)),
                         ["create", "T", "--type", "task", "--json", "--parent", "p-1", "--priority", "1", "--labels", "a,b",
                          "--no-inherit-labels"])
        self.assertEqual(update_argv("b-1", BeadPatch(status="open", assignee="", set_metadata={"k": "v"}, unset_metadata=["z"])),
                         ["update", "b-1", "--status", "open", "--assignee", "", "--set-metadata", "k=v", "--unset-metadata", "z"])

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
