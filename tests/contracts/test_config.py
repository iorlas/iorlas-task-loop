"""The repo profile (.task-loop.json): an unknown key fails loudly, a known one loads."""
import os
import sys

import pytest

from tltestkit.case import Case

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from tlkernel.config import ConfigError, RepoProfile, load


class RepoProfileKeys(Case):
    def test_merge_defaults_to_wait_and_auto_requires_pr_land(self):
        assert load({}).engine.merge == "wait"
        assert load({"engine": {"land_mode": "pr", "merge": "auto"}}).engine.merge == "auto"
        with pytest.raises(ConfigError, match=r"the repo profile: engine\.merge: auto needs engine\.land_mode: pr"):
            load({"engine": {"land_mode": "push", "merge": "auto"}})

    def test_unknown_merge_value_is_refused_naming_the_key(self):
        with pytest.raises(ConfigError, match=r"the repo profile: .*engine\.merge"):
            load({"engine": {"merge": "sometimes"}})

    def test_wait_poll_defaults_and_override_are_independent_of_child_poll(self):
        assert load({}).loop.wait_poll == 30
        tune = load({"loop": {"wait_poll": 7.5}}).loop
        assert tune.wait_poll == 7.5
        assert tune.poll == 2

    def test_run_in_defaults_to_clean_and_refuses_unknown_locations(self):
        check = {"id": "a", "argv": ["a"]}
        assert load({"engine": {"checks": [check]}}).engine.checks[0].run_in == "clean"
        assert load({"engine": {"checks": [{**check, "run_in": "slot"}]}}).engine.checks[0].run_in == "slot"
        for bad in ("worktree", "", None, 1):
            with self.subTest(bad=bad), pytest.raises(ConfigError):
                load({"engine": {"checks": [{**check, "run_in": bad}]}})

    def test_prepare_accepts_typed_argv_inputs_timeout_and_no_default_triggers(self):
        cfg = load({"engine": {"prepare": {"cmd": ["dotnet", "restore"], "inputs": ["**/*.csproj"]}}}).engine.prepare
        assert cfg is not None
        assert cfg.cmd == ["dotnet", "restore"]
        assert cfg.triggers == []
        for bad in ({"cmd": []}, {"cmd": "dotnet restore"}, {"cmd": ["x"], "timeout_min": 0},
                    {"cmd": ["x"], "unknown": True}):
            with self.subTest(bad=bad), pytest.raises(ConfigError):
                load({"engine": {"prepare": bad}})

    def test_plan_command_is_optional_and_requires_an_argv(self):
        assert load({}).engine.plan_cmd is None
        argv = ["python", "tools/gate_plan.py", "steps", "--json"]
        assert load({"engine": {"plan_cmd": argv}}).engine.plan_cmd == argv
        for bad in ([], "plan --json", [1]):
            with self.subTest(bad=bad), pytest.raises(ConfigError):
                load({"engine": {"plan_cmd": bad}})

    def test_empty_profile_is_the_defaults(self):
        assert load(None) == RepoProfile()
        assert load({}) == RepoProfile()

    def test_unknown_top_level_key_is_refused_by_name(self):
        with pytest.raises(ConfigError, match="bogus"):
            load({"bogus": 1})

    def test_unknown_engine_key_is_refused_by_name(self):
        with pytest.raises(ConfigError, match="no_such_knob"):
            load({"engine": {"no_such_knob": 1}})

    def test_a_single_argv_gate_is_refused_naming_where_the_steps_go(self):
        with pytest.raises(ConfigError, match=r"engine\.gate is gone.*engine\.checks.*\"run\": \"gate\""):
            load({"engine": {"gate": ["just", "check"]}})

    def test_gate_only_is_refused_naming_run_gate(self):
        with pytest.raises(ConfigError, match=r"engine\.gate_only is gone.*\"run\": \"gate\""):
            load({"engine": {"gate_only": [{"argv": ["just", "unity-check"]}]}})

    def test_two_ids_that_become_one_environment_name_are_refused_at_load(self):
        checks = [{"id": "unity-test", "argv": ["a"]}, {"id": "unity_test", "argv": ["b"]}]
        with pytest.raises(ConfigError, match=r"unity-test and unity_test both become \$TL_CHECK_LOG_UNITY_TEST"):
            load({"engine": {"checks": checks}})

    def test_an_id_used_twice_is_refused_at_load(self):
        with pytest.raises(ConfigError, match="check id a is used twice"):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "a", "argv": ["b"]}]}})

    def test_checks_that_read_each_other_in_a_cycle_are_refused_at_load(self):
        checks = [{"id": "a", "argv": ["a"], "reads": ["b"]}, {"id": "b", "argv": ["b"], "reads": ["a"]}]
        with pytest.raises(ConfigError, match="in a cycle"):
            load({"engine": {"checks": checks}})

    def test_a_read_of_a_check_that_is_not_there_is_refused_at_load(self):
        with pytest.raises(ConfigError, match="check a reads zzz"):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"], "reads": ["zzz"]}]}})

    def test_reads_that_form_a_graph_load(self):
        cfg = load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "b", "argv": ["b"], "reads": ["a"]}]}})
        assert cfg.engine.checks[1].reads == ["a"]

    def test_run_says_where_a_check_runs(self):
        cfg = load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "b", "argv": ["b"], "run": "gate"},
                                         {"id": "c", "argv": ["c"], "run": "both"}]}}).engine
        assert ([k.id for k in cfg.stage_checks], [k.id for k in cfg.gate_checks]) == (["a", "c"], ["b", "c"])
        with pytest.raises(ConfigError):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"], "run": "never"}]}})
