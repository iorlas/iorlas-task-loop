"""Every regular expression of the review/verify prose is a named matcher; each has a table of real wording below."""

from tlkernel import reviewkinds as kinds
from tlkernel.reviewmatchers import AcceptanceItems, BdDemand, CodeNames, EngineActions, GateProof, Tools, word_in
from tltestkit.case import Case


class Table(Case):
    def rows(self, fn, table):
        for text, want in table:
            with self.subTest(text):
                assert fn(text) == want


class ToolsTable(Table):
    def test_named(self):
        self.rows(Tools.named, [
            ("ran `ruff check tools`", ["ruff"]), ("`mypy` passes", ["mypy"]), ("checked with eslint", ["eslint"]),
            ("the biome transition", []), ("ran ruff and `flake8 .`", ["flake8", "ruff"]), ("lint the files", [])])


class CodeNamesTable(Table):
    def test_code_files_and_symbols(self):
        self.rows(lambda t: any(CodeNames.is_code_file(x) for x in CodeNames.tokens(t)),
                  [("see src/a.py for it", True), ("the README.md table", True), ("a price quoted on https://x.com/page.html", False),
                   ("the owner decides", False)])
        self.rows(
            lambda t: sorted(CodeNames.symbols(t)), [("StageLoop calls run_once", ["StageLoop", "run_once"]), ("plain words only", [])]
        )


class EngineActionsTable(Table):
    def test_filing(self):
        self.rows(
            EngineActions.files_beads,
            [
                ("File beads for the table, chairs and sink", True),
                ("Follow-up beads for each object are to be filed", True),
                ("The nine beads are not filed", True),
                ("Create a bead per object", True),
                ("file follow-up tasks", True),
                ("The beads cover all nine objects", False),
                ("The config file lists the bead ids", False),
                ("Open the bead and read it", False),
            ],
        )

    def test_lands_and_closes(self):
        self.rows(EngineActions.lands_or_closes, [("The gate runs at land", True), ("the engine closes the bead", True),
                                                  ("the engine merges", True), ("it lands well", False)])

    def test_engine_does_needs_leftovers_for_filing(self):
        assert not kinds.engine_does("File beads for the table", False)
        assert kinds.engine_does("File beads for the table", True)
        assert kinds.engine_does("The gate runs at land", False)


class BdDemandTable(Table):
    """Real send-back wording from the 50 labelled send-backs of study 81 (class e, and the mixed ones)."""

    def test_engine_only(self):
        self.rows(BdDemand.engine_only, [
            ("screenshot judgement needs a bd comment (writer barred from bd)", "bd"), ("beads to file", "bd"),
            ("close/fold 2 beads (bd action)", "bd"), ("approval + follow-up beads unfiled", "bd"),
            ("File the nine follow-up beads; the writer cannot run bd", "bd"), ("bd follow-ups unfiled", "bd"),
            ("verify the script on Windows", "os"), ("the stage goal is met", "met"), ("Nothing is missing", "met"),
            ("README table stale vs evidence", ""), ("crash file overwritten within the same second", ""),
            ("the bd store adapter swallows an error", ""),
            # the four real unmet strings of the E7 samples (tl-ogf.1)
            ("Acceptance criterion 3 asks for a play run on Windows. The engine ran only on macOS, so the Windows run is not done. "
             "The plan already lists it as a leftover.", "os"),
            ("Godot side of 'both engines' is not done (not on main); tracked as a leftover.", ""),
            ("Beads lifesim-lgye and lifesim-5ban.13 are not yet closed or folded into lifesim-yxbb.6. The task says to do this once the "
             "work is done; the coordinator does it with bd.", "bd"),
            ("The route difference from the +2 shift (bed at 7,6 instead of 5,4) is not written into bead lifesim-d5f.33 yet. The plan "
             "leaves that to the final report and the bead note.", "bd")])


class GateProofTable(Table):
    def test_says_it_passes(self):
        self.rows(
            GateProof.says_it_passes,
            [
                ("unity-tests passes", True),
                ("`just check` is green", True),
                ("ruff passed but flaky", False),
                ("a test for unity-tests", False),
                ("coverage of unity-tests runs", False),
            ],
        )

    def test_only_doubts_the_run(self):
        self.rows(GateProof.only_doubts_the_run, [
            ("cannot prove the engine ran unit-tests", True), ("cannot prove unit-tests ran, but it is flaky", False),
            ("cannot verify the ui layout of unit-tests", False), ("unit-tests passes", False)])

    def test_names(self):
        assert GateProof.check_names("cannot prove `unit-tests` and lint/x ran") == ["unit-tests", "lint/x"]
        assert GateProof.first_named("unity-tests passes", ["lint", "unity-tests"]) == "unity-tests"
        assert word_in("lint", "ran lint ok")
        assert not word_in("lint", "ran lint-all ok")


class AcceptanceItemsTable(Table):
    def test_split(self):
        self.rows(AcceptanceItems.split, [
            ("", []), ("f.txt exists", [("A1", "f.txt exists")]),
            ("  - first\n  - second\n    goes on\n", [("A1", "first"), ("A2", "second goes on")]),
            ("1. one\n2) two", [("A1", "one"), ("A2", "two")]), ("\u2022 a\n\u2022 b", [("A1", "a"), ("A2", "b")])])


class ResolveKind(Case):
    def test_a_kind_moves_only_to_a_stricter_route(self):
        yes, no = (lambda: True), (lambda: False)
        assert kinds.resolve_kind("checkable", "taste", "", no, no) == "checkable"
        assert kinds.resolve_kind("taste", "owner_decision", "", no, no) == "owner_decision"
        assert kinds.resolve_kind("engine_step", "engine_step", "", no, no) == "checkable"
        assert kinds.resolve_kind("engine_step", "engine_step", "", yes, no) == "engine_step"
        assert kinds.resolve_kind("external_fact", None, "", no, no) == "checkable"
        assert kinds.resolve_kind("external_fact", None, "https://x", no, no) == "external_fact"
        assert kinds.resolve_kind("taste", None, "", no, yes) == "checkable"
