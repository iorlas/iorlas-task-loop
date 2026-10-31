"""Repo plans select due registry checks; clean planned skips become green facts."""
import hashlib
import json
from unittest import mock

from support import engine_case as te
from support.narrow import must

from taskloop.app.checks.cache import is_green, plan_digest
from taskloop.app.checks.gateplan import PlanDecision, parse, skipped
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Ran
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items


def step(name="coverage", run=False, **extra):
    return dict(name=name, lane="tests", run=run, argv=["true"], pre=[], recipe=None, reason="no relevant change", **extra)


def document(steps=None, **extra):
    return dict(version=1, base=None, empty=False, full=False, full_reasons=[],
                steps=[step()] if steps is None else steps, **extra)


class GatePlans(te.EngineTest):
    def setup_plan(self, answer=None, checks=None):
        self.eng = self.checks_engine(plan_cmd=["repo-plan", "steps", "--json"], checks=checks or [
            {"id": "coverage", "cmd": "true", "run": "gate", "when": ["never/**"]}])
        self.answer = answer if answer is not None else Ran(exit=0, out=json.dumps(document()))
        self.calls = []

        def run(argv, **kw):
            self.calls.append((argv, kw))
            return self.answer

        self.spawned = mock.MagicMock(side_effect=run)
        patch = mock.patch.object(self.eng.spawner, "run", self.spawned)
        patch.start()
        self.addCleanup(patch.stop)

    def green(self, name, tree=None, base=None):
        host = self.eng.checker.host
        memo = self.eng.checker._memo(host.checkout.tree_hash(), host.git.rev_parse(str(host.wt), host.cfg.base))
        return is_green(memo.stores, memo.repo, CheckId(name), tree or memo.keys.tree, base or memo.base,
                        plan_digest(host.cfg.plan_cmd))

    def run_gate(self):
        return self.eng.checker.run_items(gate_items(self.eng.cfg))

    def stored(self, name, run):
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        memo = self.eng.checker._memo(run.tree, base)
        docs = memo.stores.results(memo.repo, CheckId(name))
        names = docs.keys()
        return [must(docs.of(n).get()) for n in names]

    def test_skip_is_recorded_with_reason_and_green_only_for_this_diff(self):
        self.setup_plan()
        self.assertFalse(self.green("coverage"))
        result = self.run_gate()[0]
        self.assertEqual((result.status, result.planned, result.why), ("skipped", True, "no relevant change"))
        self.assertTrue(self.green("coverage"))
        self.assertFalse(self.green("coverage", tree=TreeSha("other")))
        self.assertFalse(self.green("coverage", base=BaseSha("other")))
        self.assertTrue(self.eng.checker.gate_green())

    def test_skip_records_the_command_and_exact_printed_document_hash(self):
        self.setup_plan()
        outputs = [self.answer.out, self.answer.out + "\n"]
        for output in outputs:
            self.answer = Ran(exit=0, out=output)
            run = self.run_gate()
            self.assertEqual(run[0].status, "skipped")
        rows = self.stored("coverage", run)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.key.plan for r in rows}, {plan_digest(self.eng.cfg.plan_cmd)})
        self.assertEqual({r.key.plan_output for r in rows},
                         {hashlib.sha1(output.encode("utf-8")).hexdigest() for output in outputs})
        self.assertTrue(self.green("coverage"))

    def test_full_argv_resolved_base_checkout_and_nul_stdin(self):
        self.setup_plan()
        self.run_gate()
        argv, kw = next(c for c in self.calls if c[0][0] == "repo-plan")
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        self.assertEqual(argv, ["repo-plan", "steps", "--json", "--base", base, "--paths-stdin"])
        self.assertEqual(kw["cwd"], str(self.eng.wt))
        self.assertEqual(kw["input"], "".join(p + "\0" for p in self.eng.git.changed_paths(
            str(self.eng.wt), self.eng.git.merge_base(str(self.eng.wt), base, "HEAD"), self.eng.checkout.tree_hash())))

    def test_dirty_checkout_requires_every_step_without_running_the_plan(self):
        self.setup_plan()
        (self.wt / "uncommitted.txt").write_text("outside the judged paths\n")
        tree = self.eng.checkout.tree_hash()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        with mock.patch.object(self.eng, "warn") as warn:
            self.assertEqual(skipped(self.eng, tree, base), PlanDecision({}))
        self.assertEqual(self.calls, [])
        warn.assert_called_once_with("plan not used; every step required: checkout is dirty")

    def test_a_different_head_tree_requires_every_step_without_running_the_plan(self):
        self.setup_plan()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        with mock.patch.object(self.eng, "warn") as warn:
            self.assertEqual(skipped(self.eng, "other-tree", base), PlanDecision({}))
        self.assertEqual(self.calls, [])
        warn.assert_called_once_with("plan not used; every step required: HEAD tree differs from the judged tree")

    def test_dirty_run_items_runs_every_check_and_records_only_passes(self):
        self.setup_plan(checks=[
            {"id": name, "cmd": "true", "run": "gate", "when": ["never/**"]}
            for name in ("coverage", "lint")])
        (self.wt / "uncommitted.txt").write_text("dirty\n")
        with mock.patch.object(self.eng, "warn") as warn:
            run = self.run_gate()
        self.assertEqual([(r.status, r.planned) for r in run], [("passed", False), ("passed", False)])
        self.assertEqual(self.calls, [])
        warn.assert_called_once_with("plan not used; every step required: checkout is dirty")
        for name in ("coverage", "lint"):
            rows = self.stored(name, run)
            self.assertTrue(rows)
            self.assertTrue(all(r.result.status == "passed" and not r.key.plan and not r.key.plan_output for r in rows))

    def test_head_mismatch_run_items_runs_every_check_and_records_only_passes(self):
        self.setup_plan()
        tree = self.eng.checkout.tree_hash()
        rev_parse = self.eng.git.rev_parse
        with mock.patch.object(self.eng.git, "rev_parse", side_effect=lambda wt, ref:
                               "other-tree" if ref == "HEAD^{tree}" else rev_parse(wt, ref)), \
                mock.patch.object(self.eng, "warn") as warn:
            run = self.run_gate()
        self.assertEqual([(r.status, r.planned) for r in run], [("passed", False)])
        self.assertEqual(run.tree, tree)
        self.assertEqual(self.calls, [])
        warn.assert_called_once_with("plan not used; every step required: HEAD tree differs from the judged tree")
        rows = self.stored("coverage", run)
        self.assertTrue(rows)
        self.assertTrue(all(r.result.status == "passed" and not r.key.plan and not r.key.plan_output for r in rows))

    def test_failed_plan_requires_stage_only_checks_too(self):
        self.setup_plan(Ran(exit=1), checks=[
            {"id": "stage-only", "cmd": "true", "run": "stage", "when": ["never/**"]}])
        run = self.eng.run_checks({"checks": [], "files": []}, "stage")
        self.assertEqual([(r.status, r.planned) for r in run], [("passed", False)])
        self.assertTrue(all(r.result.status == "passed" for r in self.stored("stage-only", run)))

    def test_no_producer_preserves_legacy_when_without_checkout_guards(self):
        self.setup_plan()
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=None)
        with mock.patch.object(self.eng.git, "dirty") as dirty:
            self.assertIsNone(skipped(self.eng, "other-tree", "base"))
        dirty.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_changed_plan_argv_invalidates_a_skip_but_not_a_pass(self):
        self.setup_plan()
        self.run_gate()
        original = self.eng.cfg.plan_cmd
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["repo-plan", "steps", "--new-policy"])
        self.assertFalse(self.green("coverage"))
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=original)
        self.assertTrue(self.green("coverage"))
        self.eng.checker.run_items(gate_items(self.eng.cfg), everything=True)
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["different-plan"])
        self.assertTrue(self.green("coverage"))

    def test_run_true_and_unknown_registry_steps_remain_required_despite_when(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step(run=True)]))), checks=[
            {"id": name, "cmd": "true", "run": "gate", "when": ["never/**"]} for name in ("coverage", "unknown")])
        self.assertFalse(self.eng.checker.gate_green())
        self.assertEqual([r.status for r in self.run_gate()], ["passed", "passed"])

    def test_another_repo_step_can_be_planned_without_a_tl_code_change(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step("new-step")]))), checks=[
            {"id": "new-step", "cmd": "true", "run": "gate"}])
        self.assertEqual(self.run_gate()[0].status, "skipped")
        self.assertTrue(self.green("new-step"))

    def test_stage_round_uses_the_plan_for_both_checks_and_keeps_stage_when(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step(run=True)]))), checks=[
            {"id": "coverage", "cmd": "true", "run": "both", "when": ["never/**"]},
            {"id": "stage-only", "cmd": "true", "run": "stage", "when": ["never/**"]}])
        run = self.eng.run_checks({"checks": [], "files": []}, "stage")
        self.assertEqual([(r.id, r.status) for r in run], [("coverage", "passed"), ("stage-only", "skipped")])

    def test_failed_plans_require_every_step_and_print_one_line(self):
        answers = [Ran(exit=7), Ran(exit=124, timed_out=True), Ran(exit=0, out="not json"),
                   Ran(exit=0, out=json.dumps({**document(), "version": 2})), Ran(exit=0, out="{}")]
        self.setup_plan()
        for answer in answers:
            with self.subTest(answer=answer), mock.patch.object(self.eng, "warn") as warn:
                self.answer = answer
                self.assertEqual([r.status for r in self.run_gate()], ["passed"])
                warn.assert_called_once()
                line = warn.call_args.args[0]
                self.assertIn("plan not used; every step required:", line)
                self.assertNotIn("\n", line)

    def test_spawn_and_diff_failures_also_require_all_steps(self):
        self.setup_plan()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        tree = self.eng.checkout.tree_hash()
        failures = [[Ran(exit=0), OSError("missing producer")], [Ran(exit=1)]]
        for answers in failures:
            with self.subTest(answers=answers), mock.patch.object(self.eng, "warn") as warn:
                self.spawned.side_effect = answers
                self.assertEqual(skipped(self.eng, tree, base), PlanDecision({}))
                warn.assert_called_once()

    def test_a_red_round_never_records_its_planned_skip(self):
        self.setup_plan(checks=[{"id": "coverage", "cmd": "true", "run": "gate", "group": "static"},
                                {"id": "red", "cmd": te.FALSE, "run": "gate"}])
        self.assertTrue(self.run_gate().failed)
        self.assertFalse(self.green("coverage"))

    def test_all_bypasses_the_plan(self):
        self.setup_plan()
        run = self.eng.checker.run_items(gate_items(self.eng.cfg), everything=True)
        self.assertEqual(run[0].status, "passed")
        self.assertEqual(self.calls, [])

    def test_aliases_and_unknown_fields_are_accepted_but_missing_or_wrong_types_fail(self):
        aliased = step(optional="future", resources=["tool"])
        aliased["id"], aliased["why"] = aliased.pop("name"), aliased.pop("reason")
        self.assertEqual(parse(json.dumps(document([aliased], optional=True))).steps[0].id, "coverage")
        for key in ("lane", "run", "argv", "pre", "recipe", "name", "reason"):
            bad = step()
            del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse(json.dumps(document([bad])))
        for bad in (step(run="false"), {**step(), "argv": [1]}, {**step(), "pre": ["cmd"]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(json.dumps(document([bad])))
