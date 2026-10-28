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


if __name__ == "__main__":
    unittest.main()
