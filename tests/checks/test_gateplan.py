"""Repo plans select due registry checks; clean planned skips become green facts."""
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.check_host import CheckHostCase

from taskloop.app.checks.cache import is_green, plan_digest
from taskloop.app.checks.gateplan import PlanDecision, parse, skipped
from taskloop.domain.checks.specs import gate_items
from tlkernel.childenv import CHECK_SECRETS
from tlkernel.config import ConfigError
from tlkernel.env import Env
from tlkernel.ids import CheckId, TreeSha
from tlkernel.procport import Ran
from tlkernel.runkey import BaseSha
from tlkernel.slots import GitReadFailure
from tltestkit.narrow import must
from tltestkit.plans import FALSE


def step(name="coverage", run=False, **extra):
    return dict(name=name, lane="tests", run=run, argv=["true"], pre=[], recipe=None, reason="no relevant change", **extra)


def document(steps=None, **extra):
    return dict(version=1, base=None, empty=False, full=False, full_reasons=[],
                steps=[step()] if steps is None else steps, **extra)


class GatePlans(CheckHostCase):
    def test_plan_producer_uses_the_profile_home_mode_and_always_strips_secrets(self):
        self.setup_plan()
        secrets = {**dict.fromkeys(CHECK_SECRETS, "secret"), "GIT_CREDENTIAL_HELPER": "secret"}
        self.eng.env = Env({"HOME": "/owner", **secrets})
        self.eng.bead_env = secrets
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        tree = self.eng.checkout.tree_hash()
        for scratch_home in (False, True):
            with self.subTest(scratch_home=scratch_home):
                self.eng.cfg = self.eng.cfg.replace(check_scratch_home=scratch_home)
                assert skipped(self.eng, tree, base) is not None
                env = self.calls[-1][1]["extra"]
                assert not secrets.keys() & env.keys()
                if scratch_home:
                    assert env["HOME"] != "/owner"
                    assert not Path(env["HOME"]).exists()
                else:
                    assert env["HOME"] == "/owner"

    def test_a_plan_for_another_base_cannot_skip_checks(self):
        answer = document()
        answer["base"] = "stale-base"
        self.setup_plan(answer=Ran(exit=0, out=json.dumps(answer)))
        run = self.run_gate()
        assert run[0].status == "passed"
        assert not run[0].planned

    def test_a_plan_for_the_requested_base_retains_its_skip(self):
        self.setup_plan()
        answer = document()
        answer["base"] = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        self.answer = Ran(exit=0, out=json.dumps(answer))
        assert self.run_gate()[0].planned

    def test_failed_diff_cannot_authorize_a_legacy_when_skip(self):
        self.setup_plan()
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=None)
        with (mock.patch.object(self.eng.git, "changed_paths", side_effect=GitReadFailure("diff unavailable")),
              pytest.raises(GitReadFailure)):
            self.run_gate()
        assert not self.green("coverage")

    def test_failed_git_observations_cannot_authorize_planned_skips(self):
        self.setup_plan()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        tree = self.eng.checkout.tree_hash()
        for method in ("dirty", "rev_parse", "merge_base", "changed_paths"):
            with (self.subTest(method=method),
                  mock.patch.object(self.eng.git, method, side_effect=GitReadFailure("unreadable"))):
                assert skipped(self.eng, tree, base) == PlanDecision({})
                assert self.calls == []

    def setup_plan(self, answer=None, checks=None):
        self.eng = self.checks_engine(plan_cmd=["repo-plan", "steps", "--json"], checks=checks or [
            {"id": "coverage", "cmd": "true", "run": "gate", "when": ["never/**"]}])
        which = mock.patch("taskloop.app.checks.gateplan.shutil.which", side_effect=lambda word, **kw: word)
        which.start()
        self.addCleanup(which.stop)
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
        assert not self.green("coverage")
        result = self.run_gate()[0]
        assert (result.status, result.planned, result.why) == ("skipped", True, "no relevant change")
        assert self.green("coverage")
        assert not self.green("coverage", tree=TreeSha("other"))
        assert not self.green("coverage", base=BaseSha("other"))
        assert self.eng.checker.gate_green()

    def test_skip_records_the_command_and_exact_printed_document_hash(self):
        self.setup_plan()
        outputs = [self.answer.out, self.answer.out + "\n"]
        for output in outputs:
            self.answer = Ran(exit=0, out=output)
            run = self.run_gate()
            assert run[0].status == "skipped"
        rows = self.stored("coverage", run)  # type: ignore[unbound-name]  # the loop above runs twice
        assert len(rows) == 2
        assert {r.key.plan for r in rows} == {plan_digest(self.eng.cfg.plan_cmd)}
        assert {r.key.plan_output for r in rows} == {hashlib.sha1(output.encode("utf-8")).hexdigest() for output in outputs}
        assert self.green("coverage")

    def test_full_argv_resolved_base_checkout_and_nul_stdin(self):
        self.setup_plan()
        self.run_gate()
        argv, kw = next(c for c in self.calls if c[0][0] == "repo-plan")
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        assert argv == ["repo-plan", "steps", "--json", "--base", base, "--paths-stdin"]
        assert kw["cwd"] == str(self.eng.wt)
        assert kw["input"] == "".join(p + "\0" for p in self.eng.git.changed_paths(
            str(self.eng.wt), self.eng.git.merge_base(str(self.eng.wt), base, "HEAD"), self.eng.checkout.tree_hash()))

    def test_dirty_checkout_requires_every_step_without_running_the_plan(self):
        self.setup_plan()
        (self.wt / "uncommitted.txt").write_text("outside the judged paths\n")
        tree = self.eng.checkout.tree_hash()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        with mock.patch.object(self.eng, "warn") as warn:
            assert skipped(self.eng, tree, base) == PlanDecision({})
        assert self.calls == []
        warn.assert_called_once_with("plan not used; every step required: checkout is dirty")

    def test_a_different_head_tree_requires_every_step_without_running_the_plan(self):
        self.setup_plan()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        with mock.patch.object(self.eng, "warn") as warn:
            assert skipped(self.eng, "other-tree", base) == PlanDecision({})
        assert self.calls == []
        warn.assert_called_once_with("plan not used; every step required: HEAD tree differs from the judged tree")

    def test_dirty_run_items_runs_every_check_and_records_only_passes(self):
        self.setup_plan(checks=[
            {"id": name, "cmd": "true", "run": "gate", "when": ["never/**"]}
            for name in ("coverage", "lint")])
        (self.wt / "uncommitted.txt").write_text("dirty\n")
        with mock.patch.object(self.eng, "warn") as warn:
            run = self.run_gate()
        assert [(r.status, r.planned) for r in run] == [("passed", False), ("passed", False)]
        assert self.calls == []
        warn.assert_called_once_with("plan not used; every step required: checkout is dirty")
        for name in ("coverage", "lint"):
            rows = self.stored(name, run)
            assert rows
            assert all(r.result.status == "passed" and not r.key.plan and not r.key.plan_output for r in rows)

    def test_head_mismatch_run_items_runs_every_check_and_records_only_passes(self):
        self.setup_plan()
        tree = self.eng.checkout.tree_hash()
        rev_parse = self.eng.git.rev_parse
        with mock.patch.object(self.eng.git, "rev_parse", side_effect=lambda wt, ref:
                               "other-tree" if ref == "HEAD^{tree}" else rev_parse(wt, ref)), \
                mock.patch.object(self.eng, "warn") as warn:
            run = self.run_gate()
        assert [(r.status, r.planned) for r in run] == [("passed", False)]
        assert run.tree == tree
        assert self.calls == []
        warn.assert_called_once_with("plan not used; every step required: HEAD tree differs from the judged tree")
        rows = self.stored("coverage", run)
        assert rows
        assert all(r.result.status == "passed" and not r.key.plan and not r.key.plan_output for r in rows)

    def test_failed_plan_requires_stage_only_checks_too(self):
        self.setup_plan(Ran(exit=1), checks=[
            {"id": "stage-only", "cmd": "true", "run": "stage", "when": ["never/**"]}])
        run = self.eng.run_checks({"checks": [], "files": []}, "stage")
        assert [(r.status, r.planned) for r in run] == [("passed", False)]
        assert all(r.result.status == "passed" for r in self.stored("stage-only", run))

    def test_no_producer_preserves_legacy_when_without_checkout_guards(self):
        self.setup_plan()
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=None)
        with mock.patch.object(self.eng.git, "dirty") as dirty:
            assert skipped(self.eng, "other-tree", "base") is None
        dirty.assert_not_called()
        assert self.calls == []

    def test_changed_plan_argv_invalidates_a_skip_but_not_a_pass(self):
        self.setup_plan()
        self.run_gate()
        original = self.eng.cfg.plan_cmd
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["repo-plan", "steps", "--new-policy"])
        assert not self.green("coverage")
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=original)
        assert self.green("coverage")
        self.eng.checker.run_items(gate_items(self.eng.cfg), everything=True)
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["different-plan"])
        assert self.green("coverage")

    def test_run_true_and_unknown_registry_steps_remain_required_despite_when(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step(run=True)]))), checks=[
            {"id": name, "cmd": "true", "run": "gate", "when": ["never/**"]} for name in ("coverage", "unknown")])
        assert not self.eng.checker.gate_green()
        assert [r.status for r in self.run_gate()] == ["passed", "passed"]

    def test_another_repo_step_can_be_planned_without_a_tl_code_change(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step("new-step")]))), checks=[
            {"id": "new-step", "cmd": "true", "run": "gate"}])
        assert self.run_gate()[0].status == "skipped"
        assert self.green("new-step")

    def test_stage_round_uses_the_plan_for_both_checks_and_keeps_stage_when(self):
        self.setup_plan(Ran(exit=0, out=json.dumps(document([step(run=True)]))), checks=[
            {"id": "coverage", "cmd": "true", "run": "both", "when": ["never/**"]},
            {"id": "stage-only", "cmd": "true", "run": "stage", "when": ["never/**"]}])
        run = self.eng.run_checks({"checks": [], "files": []}, "stage")
        assert [(r.id, r.status) for r in run] == [("coverage", "passed"), ("stage-only", "skipped")]

    def test_failed_plans_require_every_step_and_print_one_line(self):
        answers = [Ran(exit=7), Ran(exit=124, timed_out=True), Ran(exit=0, out="not json"),
                   Ran(exit=0, out=json.dumps({**document(), "version": 2})), Ran(exit=0, out="{}")]
        self.setup_plan()
        for answer in answers:
            with self.subTest(answer=answer), mock.patch.object(self.eng, "warn") as warn:
                self.answer = answer
                assert [r.status for r in self.run_gate()] == ["passed"]
                warn.assert_called_once()
                line = warn.call_args.args[0]
                assert "plan not used; every step required:" in line
                assert "\n" not in line

    def test_spawn_and_diff_failures_also_require_all_steps(self):
        self.setup_plan()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        tree = self.eng.checkout.tree_hash()
        failures = [[Ran(exit=0), OSError("missing producer")], [Ran(exit=1)]]
        for answers in failures:
            with self.subTest(answers=answers), mock.patch.object(self.eng, "warn") as warn:
                self.spawned.side_effect = answers
                assert skipped(self.eng, tree, base) == PlanDecision({})
                warn.assert_called_once()

    def test_a_red_round_never_records_its_planned_skip(self):
        self.setup_plan(checks=[{"id": "coverage", "cmd": "true", "run": "gate", "group": "static"},
                                {"id": "red", "cmd": FALSE, "run": "gate"}])
        assert self.run_gate().failed
        assert not self.green("coverage")

    def test_all_bypasses_the_plan(self):
        self.setup_plan()
        run = self.eng.checker.run_items(gate_items(self.eng.cfg), everything=True)
        assert run[0].status == "passed"
        assert self.calls == []

    def test_python_uses_python3_when_only_python3_resolves(self):
        self.setup_plan()
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["python", "tools/gate_plan.py", "steps", "--json"])
        with mock.patch("taskloop.app.checks.gateplan.shutil.which", side_effect=lambda word, **kw:
                        {"python3": "/bin/python3", "git": "/usr/bin/git"}.get(word)):
            self.run_gate()
        assert self.calls[0][0][:4] == ["python3", "tools/gate_plan.py", "steps", "--json"]

    def test_python_uses_coordinator_interpreter_when_neither_spelling_exists(self):
        self.setup_plan()
        self.eng.cfg = self.eng.cfg.replace(plan_cmd=["python", "plan.py"])
        with mock.patch("taskloop.app.checks.gateplan.shutil.which", side_effect=lambda word, **kw:
                        word if word not in ("python", "python3") else None):
            self.run_gate()
        assert self.calls[0][0][0] == sys.executable

    def test_missing_executable_is_one_config_note_without_spawning(self):
        self.setup_plan()
        with mock.patch("taskloop.app.checks.gateplan.shutil.which",
                           side_effect=lambda word, **kw: "/usr/bin/git" if word == "git" else None), \
                mock.patch.object(self.eng.log, "note") as note:
            for _ in range(3):
                with pytest.raises(ConfigError, match=r"engine.plan_cmd.*repo-plan"):
                    self.run_gate()
        note.assert_called_once()
        assert self.calls == []

    def test_warning_is_once_per_run_per_reason_across_rounds(self):
        self.setup_plan()
        tree = self.eng.checkout.tree_hash()
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        with mock.patch.object(self.eng, "warn") as warn:
            for _ in range(3):
                self.answer = Ran(exit=7)
                skipped(self.eng, tree, base)
                self.answer = Ran(exit=8)
                skipped(self.eng, tree, base)
        assert warn.call_count == 2

    def test_aliases_and_unknown_fields_are_accepted_but_missing_or_wrong_types_fail(self):
        aliased = step(optional="future", resources=["tool"])
        aliased["id"], aliased["why"] = aliased.pop("name"), aliased.pop("reason")
        assert parse(json.dumps(document([aliased], optional=True))).steps[0].id == "coverage"
        for key in ("lane", "run", "argv", "pre", "recipe", "name", "reason"):
            bad = step()
            del bad[key]
            with self.subTest(key=key), pytest.raises(ValueError):
                parse(json.dumps(document([bad])))
        for bad in (step(run="false"), {**step(), "argv": [1]}, {**step(), "pre": ["cmd"]}):
            with self.subTest(bad=bad), pytest.raises(ValueError):
                parse(json.dumps(document([bad])))
