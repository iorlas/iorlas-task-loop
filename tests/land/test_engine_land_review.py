"""Engine tests: untracked files at the land, verify items the engine settles, the stage diff (tl-bxk.10.24, .19, .18)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlib import Path
from typing import cast
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.checks import res
from support.engine_case import CLEAN, PLAN, WRITE, LandReviewBase, StrayWriteScript, verdict

from taskloop.app.run import engine
from taskloop.contracts.checks import CheckRun
from taskloop.domain.look.matchers import writer_names


class LandReview(LandReviewBase):
    def test_stage_all_stages_tracked_changes_and_the_files_a_stage_lists_but_not_a_stray(self):
        self.make_files("f.txt", "docs/a/b.md", "docs/a/b.md.meta", *self.STRAY)
        (self.wt / "a.txt").write_text("changed\n")
        e = self.engine_at_land()
        self.assertEqual(e.checkout.stage_all(), 0)
        self.assertEqual(self.staged(), ["a.txt", "docs/a/b.md", "docs/a/b.md.meta", "f.txt"])
        self.assertEqual(e.newfiles.new_by_kind()["unexplained"], self.STRAY)

    def test_an_untracked_file_the_writer_names_or_a_review_accepts_is_staged(self):
        self.make_files("g.txt", *self.STRAY)
        e = self.engine_at_land({"writer_said": "I also added g.txt for the fixture",
                                 "accepted_new": [self.STRAY[0]]})  # the .meta follows its file
        e.checkout.stage_all()
        self.assertEqual(self.staged(), sorted(["g.txt", *self.STRAY]))

    def test_writer_said_matches_the_path_or_basename_on_word_boundaries(self):
        e = self.engine_at_land({"writer_said": "added tools/g.txt, and `h.cfg`. Not ab.md or c.txt.bak"})
        self.assertTrue(writer_names("tools/g.txt", e.writer_said))
        self.assertTrue(writer_names("other/g.txt", e.writer_said))  # the basename
        self.assertTrue(writer_names("h.cfg", e.writer_said))
        self.assertFalse(writer_names("b.md", e.writer_said))
        self.assertFalse(writer_names("c.txt", e.writer_said))
        self.assertFalse(writer_names("tools/g", e.writer_said))

    def test_a_replanned_first_stage_starts_from_the_current_tree_not_the_task_base(self):
        e = self.engine_at_land({"stage_tree": "old", "amended": True})
        with (
            mock.patch.object(e.checkout, "tree_hash", return_value="T"),
            mock.patch.object(e.checkpoints, "save", side_effect=RuntimeError("stop")),
            self.assertRaises(RuntimeError),
        ):
            e.stage_loop.run({"stages": [{"goal": "g", "files": [], "checks": [], "hard": False}]}, 0)
        self.assertEqual(e.stage_tree, "T")

    def test_untracked_ignore_globs_are_never_staged_nor_listed_even_when_a_stage_lists_the_folder(self):
        self.make_files("docs/keep.md", "docs/junk.tmp", *self.STRAY)
        e = self.engine_at_land({"accepted_new": [self.STRAY[0]]}, untracked_ignore=["client/Assets/InitTestScene*.unity*", "*.tmp"])
        e.checkout.stage_all()
        self.assertEqual(self.staged(), ["docs/keep.md"])
        kinds = e.newfiles.new_by_kind()
        self.assertEqual((kinds["unexplained"], sorted(kinds["ignored"])), ([], sorted(["docs/junk.tmp", *self.STRAY])))

    def test_a_stray_scene_is_listed_for_the_review_and_left_out_of_the_land(self):
        script = StrayWriteScript({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, reject_files=[self.STRAY[0]])]})
        self.assertEqual(self.run_with(script), 0)
        brief = next(p for c, p in zip(script.calls, script.prompts, strict=False) if c[0] == "reviewer")
        self.assertIn("Unexplained new files", brief)
        for p in self.STRAY:
            self.assertIn("- " + p, brief)
        self.assertIn("scene", brief)  # the content is in the brief
        self.assertEqual(self.landed(), ["f.txt"])

    def test_a_stray_the_review_does_not_decide_is_a_finding_never_a_silent_drop(self):
        script = StrayWriteScript({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, dict(CLEAN, reject_files=[self.STRAY[0]])]})
        self.assertEqual(self.run_with(script), 0)
        writes = [p for c, p in zip(script.calls, script.prompts, strict=False) if c[0] == "worker"]
        self.assertIn("decide: unexplained new file " + self.STRAY[0], writes[1])

    def test_the_gate_runs_without_the_stray_which_is_kept_in_evidence_and_traced(self):
        self.make_files("f.txt", "docs/x.md", *self.STRAY)
        (self.wt / "bin.dat").write_bytes(b"\0\1\2")
        e = self.engine_at_land()
        self.assertEqual(e.newfiles.new_file_view("bin.dat"), "binary, 3 bytes")
        (self.wt / "long.txt").write_text("".join(f"l{i}\n" for i in range(100)))
        v = e.newfiles.new_file_view("long.txt")
        self.assertIn("l79", v)
        self.assertNotIn("l80\n", v)
        self.assertIn("20 more lines", v)
        e.comment = mock.Mock()
        moved = e.newfiles.quarantine_strays()
        self.assertEqual(sorted(moved), sorted([*self.STRAY, "bin.dat", "long.txt"]))
        for p in self.STRAY:
            self.assertFalse((self.wt / p).exists())
            self.assertTrue((e.evidence_dir / "strays" / p).is_file())
        self.assertTrue((self.wt / "f.txt").exists())
        self.assertEqual(e.strays, moved)
        self.assertIn("kept", e.comment.call_args[0][0])

    def test_untracked_ignore_files_are_never_moved(self):
        self.make_files(*self.STRAY)
        e = self.engine_at_land(untracked_ignore=["client/Assets/InitTestScene*.unity*"])
        e.comment = mock.Mock()
        self.assertEqual(e.newfiles.quarantine_strays(), [])
        self.assertTrue((self.wt / self.STRAY[0]).exists())

    def test_a_stray_scene_the_reviewer_accepts_lands_with_its_meta(self):
        script = StrayWriteScript({"plan": [PLAN], "write": [WRITE],
                                   "review": [dict(CLEAN, accept_files=[self.STRAY[0], "no/such"])]})
        self.assertEqual(self.run_with(script), 0)
        self.assertEqual(self.landed(), sorted(["f.txt", *self.STRAY]))

    def test_items_whose_proof_is_the_gate_or_a_stage_check_are_settled_and_never_asked(self):
        # lifesim-5ban.1, 10-22 05:32: blocked on 'could not check: unity-analyzers/unity-tests/unity-play-tests'
        e = self.verifier(checks=self.CFG_CHECKS, gate="just check")
        items = [{"what": w, "kind": "tooling"} for w in (
            "just unity-analyzers, unity-tests, unity-play-tests: engine-run, no client changes",
            "unity-play-tests ran green", "just check is green")]
        with mock.patch.object(e, "ai") as ai:
            self.assertEqual(e.verifier.run(items), [])
        ai.assert_not_called()  # no verifier call: the engine proves them
        self.assertEqual([v["verdict"] for v in e.verified], ["settled"] * 3)
        self.assertIn("gate", e.verified[0]["evidence"])

    def test_scenario_items_are_settled_only_when_a_scenario_check_is_configured(self):
        item = [{"what": "just scenarios passes", "kind": "tooling"}]
        e = self.verifier(checks=self.CFG_CHECKS)
        with mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="a person")]}, None)):
            self.assertEqual(len(e.verifier.run(item)), 1)
        e = self.verifier(checks=[{"id": "scenarios", "cmd": "just scenarios", "group": "tests"}])
        with mock.patch.object(e, "ai") as ai:
            self.assertEqual(e.verifier.run(item), [])
        ai.assert_not_called()

    def test_items_about_coverage_skips_or_fakes_are_never_settled_but_a_pass_is(self):
        asks = ["An editor left open makes just unity-tests at the land gate exit 0 as SKIPPED (a false green)",
                "A real Unity rebuild through `just unity-check` ... only the fake-UNITY path is tested",
                "Diff coverage: ... must be covered by tests, or just coverage fails"]
        cfg = [
            *self.CFG_CHECKS,
            {"id": "coverage", "cmd": "just coverage", "group": "tests"},
            {"id": "unity-check", "cmd": "just unity-check", "group": "tests"},
        ]
        e = self.verifier(checks=cfg, gate="just check")
        with mock.patch.object(e, "ai", return_value=({"items": [verdict(i + 1, "open", why="x") for i in range(3)]}, None)):
            left = e.verifier.run([{"what": a, "kind": "tooling"} for a in asks])
        self.assertEqual(len(left), 3)
        e = self.verifier(checks=cfg, gate="just check")
        with mock.patch.object(e, "ai") as ai:
            self.assertEqual(e.verifier.run([{"what": "just unity-tests passes", "kind": "tooling"}]), [])
        ai.assert_not_called()

    def test_a_stage_check_of_the_plan_settles_an_item_naming_it(self):
        e = self.verifier()
        e.plan_data["stages"][0]["checks"] = ["python3 tools/check_design.py"]
        items = [{"what": "python3 tools/check_design.py passes", "kind": "tooling"},
                 {"what": "the menu reads well", "kind": "requirement"}]
        with mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="taste")]}, None)) as ai:
            left = e.verifier.run(items)
        self.assertEqual([u["what"] for u in left], ["the menu reads well"])
        self.assertEqual(ai.call_count, 1)
        self.assertNotIn("check_design", ai.call_args[0][2])

    def test_an_item_naming_a_linter_the_repo_has_is_run_and_its_exit_settles_it(self):
        (self.wt / "justfile").write_text("lint:\n    ruff check tools\n")
        e = self.verifier()
        item = {"what": "nobody ran `ruff check tools` on the new module", "kind": "tooling"}
        with mock.patch.object(engine, "tool_on_path", return_value="/bin/ruff"), \
                mock.patch.object(e, "sh", return_value=(0, "")) as sh_, mock.patch.object(e, "ai") as ai:
            self.assertEqual(e.verifier.run([item]), [])
        self.assertEqual(sh_.call_args[0][0], ["ruff", "check", "--no-fix", "."])
        ai.assert_not_called()
        self.assertEqual(e.verified[0]["verdict"], "settled")
        self.assertIn("exit 0", e.verified[0]["evidence"])

    def test_a_linter_that_fails_is_wrong_and_one_that_cannot_start_stays_with_the_verifier(self):
        (self.wt / "justfile").write_text("lint:\n    ruff check tools\n")
        item = {"what": "nobody ran ruff on tools/*.py", "kind": "tooling"}
        for rc in (1, 127):
            e = self.verifier(max_fix_rounds=0)
            with mock.patch.object(engine, "tool_on_path", return_value="/bin/ruff"), \
                    mock.patch.object(e, "sh", return_value=(rc, "E501 line too long")) as sh_, \
                    mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="x")]}, None)) as ai:
                left = e.verifier.run([item])
            self.assertEqual(sh_.call_args[0][0], ["ruff", "check", "--no-fix", "."])
            self.assertEqual(len(left), 1)
            if rc == 1:
                ai.assert_not_called()
                self.assertEqual(e.verified[0]["verdict"], "wrong")
                self.assertIn("E501", left[0]["why"])
            else:
                self.assertEqual(ai.call_count, 1)

    def test_an_item_naming_a_write_flag_never_runs_it(self):
        (self.wt / "justfile").write_text("lint:\n    ruff check tools\n    prettier --check .\n")
        for what, argv in (("nobody ran `ruff check --fix .`", ["ruff", "check", "--no-fix", "."]),
                           ("nobody ran `prettier --write .`", ["prettier", "--check", "."])):
            e = self.verifier(max_fix_rounds=0)
            with mock.patch.object(engine, "tool_on_path", return_value="/bin/x"), \
                    mock.patch.object(e, "sh", return_value=(0, "")) as sh_, mock.patch.object(e, "ai"):
                e.verifier.run([{"what": what, "kind": "tooling"}])
            self.assertEqual([c[0][0] for c in sh_.call_args_list], [argv])

    def test_shell_syntax_in_a_backticked_command_is_never_run(self):
        e = self.engine_at_land()
        (self.wt / "justfile").write_text("lint:\n    ruff check tools\n")
        with mock.patch.object(engine, "tool_on_path", return_value="/bin/ruff"):
            self.assertEqual(e.settles.lint_command("`ruff check . ; rm -rf ~` was not run"), ("ruff", "check", "--no-fix", "."))
            self.assertEqual(e.settles.lint_command("`ruff check --fix .` was not run"), ("ruff", "check", "--no-fix", "."))
            self.assertEqual(e.settles.lint_command("`prettier --write .` was not run"), ("prettier", "--check", "."))
            self.assertIsNone(e.settles.lint_command("`tsc --build` was not run"))

    def test_the_yxbb6_item_is_not_settled_by_a_suite_name_but_the_brief_carries_the_evidence_and_the_skip_rule(self):
        e = self.evidenced(attrs={"run_dir": Path("/runs/x")})
        with mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="x")]}, None)) as ai:
            self.assertEqual(len(e.verifier.run([{"what": self.YXBB6, "kind": "tooling"}])), 1)
        brief = ai.call_args[0][2]
        self.assertIn("`unity-tests` [tests] skipped (no change under client/**, content/**)", brief)
        self.assertIn("Sim.Properties", brief)
        self.assertIn("proven by design", brief)
        self.assertIn("log checks/06-tests_Sim.Properties.r2.log", brief)
        self.assertNotIn("/runs/x", brief)

    def test_an_item_whose_only_doubt_is_the_log_of_a_green_or_path_skipped_check_id_is_settled(self):
        for what in ("`unity-tests`: no saved log, so I cannot prove it", "unity-analyzers: there is no log, so I cannot prove it"):
            e = self.evidenced()
            with mock.patch.object(e, "ai") as ai:
                self.assertEqual(e.verifier.run([{"what": what, "kind": "tooling"}]), [], what)
            ai.assert_not_called()
            v = e.verified[0]
            self.assertEqual(v["verdict"], "settled")
            self.assertIn("does not apply", v["evidence"])
            self.assertEqual(v["why"], "the engine's own check results settle it")

    def test_wrong_settles_are_refused(self):
        cannot = ", so I cannot prove it"
        asks = ["unity-tests did not run the new test", "Sim.Properties ran, new property test isn't in it",
                "unity-tests passed, though test X is flaky",
                "unity-tests skipped, yet I changed client/Assets via a symlink", "unity-tests was not run",
                "ruff and unity-play-tests passed" + cannot, "unity-tests passed" + cannot + ", but test X is flaky",
                "unity-tests passed, no saved log, but nothing tests the new case",
                "unit tests for the new function were never run" + cannot,
                "unity-tests and unity-*: no saved log" + cannot, "the Sim.Properties suite passed" + cannot]
        for what in asks:
            e = self.evidenced([*self.engine_checks(), res("pytest tests/unit", 0, id="test", secs=1, log="checks/x.log")])
            with mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="x")]}, None)) as ai:
                self.assertEqual(len(e.verifier.run([{"what": what, "kind": "tooling"}])), 1, what)
            self.assertEqual(ai.call_count, 1, what)

    def test_a_red_check_an_older_tree_or_an_unknown_tree_settles_nothing(self):
        what = "`unity-tests`: no saved log, so I cannot prove it"
        for how in ("red", "older", "unknown"):
            e = self.evidenced(self.engine_checks(**({"unity-tests": {"exit": 1, "status": "failed", "why": ""}} if how == "red" else {})))
            if how == "older":
                e.last_run = cast(CheckRun, e.last_run).replace(tree="0" * 40)
            if how == "unknown":
                e.last_run = None
                e.run_dir = Path(self.tmp.name, "nope")
            with mock.patch.object(e, "ai", return_value=({"items": [verdict(1, "open", why="x")]}, None)) as ai:
                self.assertEqual(len(e.verifier.run([{"what": what, "kind": "tooling"}])), 1, how)
            self.assertEqual(ai.call_count, 1, how)

    def test_the_brief_lists_at_most_30_checks_of_300_characters(self):
        e = self.evidenced([res("x" * 900, 0, id=f"c{i}", secs=1, log="checks/l.log") for i in range(40)])
        text = e.settles.evidence_text()
        rows = [ln for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(rows), 31)
        self.assertTrue(all(len(ln) <= 300 for ln in rows))
        self.assertIn("10 more checks", rows[-1])

    def test_the_review_brief_inlines_the_stage_diff_ahead_of_the_checks(self):
        brief = self.reviewer_brief()
        self.assertIn("<diff>", brief)
        self.assertIn("+d2", brief)  # the writer's f.txt
        self.assertLess(brief.index("<diff>"), brief.index("The engine ran the checks"))
        self.assertNotIn("git diff", brief)
        self.assertIn("AGENTS.md or CLAUDE.md", brief)

    def test_over_the_cap_the_brief_gives_the_stat_and_tells_the_reviewer_to_read_only_the_changed_files(self):
        brief = self.reviewer_brief(cap=5)
        self.assertNotIn("<diff>", brief)
        self.assertIn("too big to inline", brief)
        self.assertIn("f.txt | 1 +", brief)
        self.assertIn("Read only the changed files plus the plan", brief)

    def test_the_diff_of_a_later_stage_starts_where_that_stage_started(self):
        e = self.engine_at_land()
        (self.wt / "one.txt").write_text("stage one\n")
        self.assertIn("one.txt", e.newfiles.stage_work([], []))
        e.stage_tree = e.checkout.tree_hash()  # stage 2 starts here
        self.assertIn("no file changed", e.newfiles.stage_work([], []))
        (self.wt / "two.txt").write_text("stage two\n")
        work = e.newfiles.stage_work([], [])
        self.assertIn("two.txt", work)
        self.assertNotIn("one.txt", work)

    def test_a_stray_file_is_not_in_the_stage_diff(self):
        e = self.engine_at_land()
        self.make_files("f.txt", *self.STRAY)
        work = e.newfiles.stage_work(self.STRAY, [])
        self.assertIn("f.txt", work)
        self.assertNotIn("InitTestScene", work)
