"""The repo profile (.task-loop.json): an unknown key fails loudly, a known one loads."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from taskloop.contracts.config import ConfigError, RepoProfile, load


class RepoProfileKeys(unittest.TestCase):
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

    def test_run_says_where_a_check_runs(self):
        cfg = load({"engine": {"checks": [{"id": "a", "argv": ["a"]}, {"id": "b", "argv": ["b"], "run": "gate"},
                                         {"id": "c", "argv": ["c"], "run": "both"}]}}).engine
        self.assertEqual(([k.id for k in cfg.stage_checks], [k.id for k in cfg.gate_checks]), (["a", "c"], ["b", "c"]))
        with self.assertRaises(ConfigError):
            load({"engine": {"checks": [{"id": "a", "argv": ["a"], "run": "never"}]}})


if __name__ == "__main__":
    unittest.main()
