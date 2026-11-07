"""adapters/bd.py: the shared Beads contract on the fake and on real bd (a throwaway database; skipped without bd), the golden
bd 1.3.1 outputs through the real adapter's parser (the process replaced by the captured text), and logic tests on the fake."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support.case import Case
from support.tmpdir import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from ports.beads_contract import BeadsContract
from support.fake_beads import FakeBeads
from support.tags import contract, domain

from taskloop.adapters import bd
from taskloop.adapters.bd import BdRun, BdStore
from taskloop.contracts.bead import BdError
from taskloop.contracts.beadsport import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead
from taskloop.contracts.ids import BeadId

GOLD = Path(__file__).parent / "golden" / "bd_1_3_1"


def gold(name: str) -> str:
    return (GOLD / name).read_text(encoding="utf-8")


@contract
class FakeBeadsContract(BeadsContract, Case):
    def make(self) -> FakeBeads:
        return FakeBeads(actor=self.ACTOR)


@contract
class RealBdContract(BeadsContract, Case):
    """One `bd init` (13 s) for the class; every test makes its own beads and lists only what it created, so the
    database is shared. Skipped when bd is not installed or cannot init."""

    root: str = ""
    why_not: str = ""  # a skip is per test, never in setUpClass: unittest does not count the tests of a class skipped there,
    # and the release gate fails a run whose count differs from the planned one

    @classmethod
    def setup_class(cls) -> None:
        exe = shutil.which("bd")
        if not exe:
            cls.why_not = "bd is not installed"
            return
        cls.root = mkdtemp(prefix="ports-bd-")
        subprocess.run(["git", "init", "-q"], cwd=cls.root, check=True)
        r = subprocess.run([exe, "init", "--quiet", "--prefix", "pt"], cwd=cls.root, capture_output=True, text=True,
                           env=dict(os.environ, HOME=cls.root), check=False)
        if r.returncode != 0:
            shutil.rmtree(cls.root, ignore_errors=True)
            cls.root = ""
            cls.why_not = f"bd init failed: {r.stderr[-200:]}"

    def setup_method(self) -> None:
        if self.why_not:
            pytest.skip(self.why_not)
        super().setup_method()

    @classmethod
    def teardown_class(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def make(self) -> BdStore:
        return BdStore(actor=self.ACTOR, cwd=self.root)


@contract
class GoldenBd(Case):
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
        b = self.beads(show=BdRun(0, gold("show_in_progress.json"), "")).show(BeadId("t-gold"))
        assert b is not None
        assert (b.status, b.assignee, b.metadata) == ("in_progress", "x", {"slot": "s1", "held_bead": "t-dhc"})
        assert b.lease_expires_at

    def test_a_fenced_close_guards_with_a_same_value_update_then_closes_with_the_reason(self) -> None:
        b = self.beads(update=BdRun(0, "", ""), close=BdRun(0, "", ""))
        b.close(BeadId("t-1"), "landed", if_assignee="loop")
        assert [c[3:] for c in b.calls] == [  # type: ignore[attr-defined]
            ["update", "t-1", "--if-assignee", "loop", "--assignee", "loop", "--json"], ["close", "t-1", "--reason", "landed", "--json"]]

    def test_a_fenced_close_on_a_moved_bead_never_closes(self) -> None:
        b = self.beads(update=BdRun(13, "", "assignee mismatch"))
        with pytest.raises(BdFailure):
            b.close(BeadId("t-1"), "landed", if_assignee="loop")
        assert [c[3] for c in b.calls] == ["update"]  # type: ignore[attr-defined]

    def test_show_missing_is_none(self) -> None:
        assert self.beads(show=BdRun(1, gold("show_missing.out"), gold("show_missing.err"))).show(BeadId("nope")) is None

    def test_malformed_successful_bead_reads_raise_with_raw_evidence(self) -> None:
        outputs = ("not JSON", '[{"id":', "null", "false", "42", '"text"', "{}", '{"issues": []}',
                   '[{"id": "t-1"}, null]', '[{"id": "t-1"}, {}]', '[{"id": "t-1"}, "row"]',
                   '[{"id": "t-1"}, {"id": "-bad"}]', '{"id": null}', '{"id": 12}', '{"id": ""}')
        for output in outputs:
            for command in ("show", "list", "ready"):
                if command == "show" and "-bad" in output:  # show answers one bead: the client reads its first row only
                    continue
                with self.subTest(output=output, command=command):
                    raw = " \n" + output + " \n"
                    store = self.beads(**{command: BdRun(0, raw, "")})
                    with pytest.raises(BdFailure) as cm:
                        if command == "show":
                            store.show(BeadId("t-1"))
                        elif command == "list":
                            store.find(BeadQuery())
                        else:
                            store.ready()
                    assert cm.value.error.kind == "malformed"
                    assert "-bad" in output or cm.value.error.text == raw.strip()[:500]  # a bad id: no raw text

    def test_empty_reads_are_missing_and_sparse_rows_still_decode(self) -> None:
        store = self.beads(show=BdRun(0, "[]", ""), list=BdRun(0, "[]", ""), ready=BdRun(0, "[]", ""))
        assert store.show(BeadId("t-1")) is None
        assert store.find(BeadQuery()) == []
        assert store.ready() == []
        for output in ('{"id": "t-1"}', '[{"id": "t-1"}]'):
            with self.subTest(output=output):
                shown = self.beads(show=BdRun(0, output, "")).show(BeadId("t-1"))
                assert shown is not None
                assert (shown.id, shown.title, shown.status, shown.labels) == ("t-1", "", "", [])

    def test_blank_collection_reads_are_empty_but_blank_show_is_malformed(self) -> None:
        for output in ("", " \n\t"):
            with self.subTest(output=output):
                store = self.beads(**{cmd: BdRun(0, output, "") for cmd in ("show", "list", "ready")})
                assert store.find(BeadQuery()) == []
                assert store.ready() == []
                with pytest.raises(BdFailure) as cm:
                    store.show(BeadId("t-1"))
                assert cm.value.error.kind == "malformed"

    def test_successful_writes_accept_plain_words_without_read_validation(self) -> None:
        store = self.beads(update=BdRun(0, "Updated issue", ""), unclaim=BdRun(0, "Unclaimed issue", ""),
                           heartbeat=BdRun(0, "Lease renewed", ""), close=BdRun(0, "Closed issue", ""))
        bead = BeadId("t-1")
        store.update(bead, BeadPatch(status="open"))
        assert store.claim(bead)
        assert store.unclaim(bead)
        store.heartbeat(bead)
        store.close(bead, "done")

    def test_malformed_evidence_is_clipped_after_trimming(self) -> None:
        raw = " \n" + "broken" * 100 + " \n"
        with pytest.raises(BdFailure) as cm:
            self.beads(show=BdRun(0, raw, "")).show(BeadId("t-1"))
        assert cm.value.error.text == raw.strip()[:500]

    def test_comments(self) -> None:
        got = self.beads(comments=BdRun(0, gold("comments.json"), "")).comments(BeadId("t-eis"))
        assert [(c.author, c.text) for c in got] == [("x", "hi there")]

    def test_list_and_ready(self) -> None:
        got = self.beads(list=BdRun(0, gold("list_open_and_in_progress.json"), ""), ready=BdRun(0, gold("ready.json"), ""))
        assert [b.id for b in got.find(BeadQuery())] == ["t-dhc"]
        assert [b.id for b in got.ready()] == ["t-dhc"]

    def test_closed_list_reads_status_and_sorted_labels(self) -> None:
        got = self.beads(list=BdRun(0, gold("list_closed.json"), "")).find(BeadQuery(status="closed"))
        assert [(b.id, b.status, b.labels) for b in got] == [("t-eis", "closed", ["a", "slot"])]

    def test_create_answer_gives_the_id(self) -> None:
        assert self.beads(create=BdRun(0, gold("create.json"), "")).create(NewBead(title="gold")) == "t-gold"

    def test_a_closed_bead_claim_is_refused_with_no_exception(self) -> None:
        assert not self.beads(update=BdRun(1, gold("claim_closed.out"), gold("claim_closed.err"))).claim(BeadId("t-eis"))

    def test_error_kinds(self) -> None:
        assert bd.error_of(gold("claim_closed.err"), "").kind == "not_claimable"
        assert bd.error_of(gold("show_missing.err"), gold("show_missing.out")).kind == "not_found"
        lint = bd.error_of(gold("create_lint_refused.err"), "")
        assert (lint.kind, lint.missing_sections) == ("lint", ["Acceptance Criteria", "Touches"])

    def test_a_refused_create_raises_with_the_sections(self) -> None:
        b = self.beads(create=BdRun(1, "", gold("create_lint_refused.err")))
        with pytest.raises(BdFailure) as cm:
            b.create(NewBead(title="t"))
        assert cm.value.error.missing_sections == ["Acceptance Criteria", "Touches"]

    def test_dependencies_read_the_same_from_show_and_list(self) -> None:
        shown = self.beads(show=BdRun(0, gold("show_blocked_by.json"), "")).show(BeadId("zz-kgz"))
        listed = self.beads(list=BdRun(0, gold("list_with_parent_dep.json"), "")).find(BeadQuery(label="a"))[0]
        assert shown is not None
        assert [(d.id, d.type, d.title, d.status) for d in shown.dependencies] == [("zz-6to.1", "blocks", "Child", "in_progress")]
        assert [(d.id, d.type) for d in listed.dependencies] == [("zz-6to", "parent-child")]
        assert listed.parent == "zz-6to"

    def test_every_call_carries_the_actor_and_json(self) -> None:
        store = self.beads(show=BdRun(0, gold("show_open.json"), ""), comments=BdRun(0, "[]", ""), update=BdRun(0, "[]", ""))
        store.show(BeadId("x"))
        store.comments(BeadId("x"))
        store.claim(BeadId("x"))
        store.update(BeadId("x"), BeadPatch(status="open"))
        for argv in store.calls:  # type: ignore[attr-defined]
            assert (argv[1], argv[2], argv[-1]) == ("--actor", "x", "--json"), argv

    def test_error_text_comes_from_bds_json_error_key(self) -> None:
        assert bd.error_of(gold("claim_taken.err"), gold("claim_taken.out")).kind == "not_claimable"
        assert bd.error_of("", gold("show_missing_json.out")).kind == "not_found"
        assert bd.error_of(gold("provenance_refused.err"), gold("provenance_refused.out")).kind == "other"
        assert "unknown kind" in bd.error_of("", gold("provenance_refused.out")).text

    def test_provenance_argv(self) -> None:
        store = self.beads(provenance=BdRun(0, "{}", ""))
        store.provenance(BeadId("b-1"), "k", "tl", at="2026-01-01T00:00:00Z")
        assert store.calls[0][3:7] == ["provenance", "record", "--issue", "b-1"]  # type: ignore[attr-defined]

    REJECTED = ("error: failed to push some refs to 'git+https://x/y.git'\nhint: Updates were rejected because the tip of your "
                "current branch is behind")

    def test_a_dolt_push_bd_rejects_with_exit_0_fails(self) -> None:
        store = self.beads(sync=BdRun(0, "", self.REJECTED), dolt=BdRun(0, "", self.REJECTED))
        assert store.dolt_push().code == 1
        assert "Updates were rejected" in store.dolt_push().text
        assert store.passthrough(["dolt", "push"]).code == 1

    def test_a_sync_conflict_keeps_bds_words_and_code(self) -> None:
        words = "merge conflict in tables: child_counters, issues"
        assert self.beads(sync=BdRun(2, "", words)).dolt_push() == DoltPush(2, words)

    def test_a_synced_push_is_ok_and_runs_bd_sync(self) -> None:
        store = self.beads(sync=BdRun(0, "", "Pushing to Dolt remote..."), dolt=BdRun(0, "", "Pushing to Dolt remote..."))
        assert store.dolt_push().code == 0
        assert store.calls[0][3:] == ["sync", "--no-adopt", "--json"]  # type: ignore[attr-defined]
        assert store.passthrough(["dolt", "push"]).code == 0

    def test_every_golden_file_is_json_or_text(self) -> None:
        for f in GOLD.glob("*.json"):
            json.loads(f.read_text(encoding="utf-8"))


@domain
class FakeBeadsLogic(Case):
    def test_a_scripted_create_refusal_then_success(self) -> None:
        beads = FakeBeads()
        beads.refuse_create.append(BdError(kind="lint", missing_sections=["Touches"]))
        with pytest.raises(BdFailure) as cm:
            beads.create(NewBead(title="t"))
        assert cm.value.error.missing_sections == ["Touches"]
        assert beads.create(NewBead(title="t")) == "fk-1"

    def test_a_dependency_keeps_a_bead_off_ready_until_it_closes(self) -> None:
        beads = FakeBeads()
        first = beads.create(NewBead(title="first"))
        second = beads.create(NewBead(title="second", deps=[first]))
        assert [b.id for b in beads.ready()] == [first]
        beads.close(first, "done")
        assert [b.id for b in beads.ready()] == [second]
