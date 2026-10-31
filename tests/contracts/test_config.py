"""The repo profile (.task-loop.json): an unknown key fails loudly, a known one loads."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from taskloop.contracts.config import ConfigError, RepoProfile, load


class RepoProfileKeys(unittest.TestCase):
    def test_plan_command_is_optional_and_requires_an_argv(self):
        self.assertIsNone(load({}).engine.plan_cmd)
        argv = ["python", "tools/gate_plan.py", "steps", "--json"]
        self.assertEqual(load({"engine": {"plan_cmd": argv}}).engine.plan_cmd, argv)
        for bad in ([], "plan --json", [1]):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                load({"engine": {"plan_cmd": bad}})

    def test_empty_profile_is_the_defaults(self):
        self.assertEqual(load(None), RepoProfile())
        self.assertEqual(load({}), RepoProfile())

    def test_unknown_top_level_key_is_refused_by_name(self):
        with self.assertRaisesRegex(ConfigError, "bogus"):
            load({"bogus": 1})

    def test_unknown_engine_key_is_refused_by_name(self):
        with self.assertRaisesRegex(ConfigError, "no_such_knob"):
            load({"engine": {"no_such_knob": 1}})

    def test_a_single_argv_gate_is_refused_naming_where_the_steps_go(self):
        with self.assertRaisesRegex(ConfigError, r"engine\.gate is gone.*engine\.checks.*\"run\": \"gate\""):
            load({"engine": {"gate": ["just", "check"]}})

    def test_gate_only_is_refused_naming_run_gate(self):
        with self.assertRaisesRegex(ConfigError, r"engine\.gate_only is gone.*\"run\": \"gate\""):
            load({"engine": {"gate_only": [{"argv": ["just", "unity-check"]}]}})

    def test_two_ids_that_become_one_environment_name_are_refused_at_load(self):
        checks = [{"id": "unity-test", "argv": ["a"]}, {"id": "unity_test", "argv": ["b"]}]
        with self.assertRaisesRegex(ConfigError, r"unity-test and unity_test both become \$TL_CHECK_LOG_UNITY_TEST"):
            load({"engine": {"checks": checks}})

    def test_an_id_used_twice_is_refused_at_load(self):
        with self.assertRaisesRegex(ConfigError, "check id a is used twice"):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "a", "argv": ["b"]}]}})

    def test_checks_that_read_each_other_in_a_cycle_are_refused_at_load(self):
        checks = [{"id": "a", "argv": ["a"], "reads": ["b"]}, {"id": "b", "argv": ["b"], "reads": ["a"]}]
        with self.assertRaisesRegex(ConfigError, "in a cycle"):
            load({"engine": {"checks": checks}})

    def test_a_read_of_a_check_that_is_not_there_is_refused_at_load(self):
        with self.assertRaisesRegex(ConfigError, "check a reads zzz"):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"], "reads": ["zzz"]}]}})

    def test_reads_that_form_a_graph_load(self):
        cfg = load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "b", "argv": ["b"], "reads": ["a"]}]}})
        self.assertEqual(cfg.engine.checks[1].reads, ["a"])

    def test_run_says_where_a_check_runs(self):
        cfg = load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "b", "argv": ["b"], "run": "gate"},
                                         {"id": "c", "argv": ["c"], "run": "both"}]}}).engine
        self.assertEqual(([k.id for k in cfg.stage_checks], [k.id for k in cfg.gate_checks]), (["a", "c"], ["b", "c"]))
        with self.assertRaises(ConfigError):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"], "run": "never"}]}})


if __name__ == "__main__":
    unittest.main()
