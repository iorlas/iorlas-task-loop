"""engine.writer_family and the label writer-family:<f> (domain/lanes/pin.py): who is pinned, which roles carry the flag."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import delegate
from taskloop.domain.lanes import pin


class Pin(unittest.TestCase):
    def test_the_profile_pins_and_a_bead_label_overrides_it(self):
        self.assertEqual(pin.families(["openai"], ["x"]), ["openai"])
        self.assertEqual(pin.families(["openai"], ["writer-family:xai"]), ["xai"])
        self.assertEqual(pin.families([], ["writer-family:OpenAI", "writer-family:xai"]), ["openai", "xai"])
        self.assertEqual(pin.families([], ["writer-family:"]), [])
        self.assertEqual(pin.families([], []), [])

    def test_only_the_worker_role_carries_the_pin(self):
        self.assertEqual(pin.for_role("worker", ["openai"]), ["openai"])
        self.assertEqual([pin.for_role(r, ["openai"]) for r in ("planner", "reviewer")], [[], []])

    def test_the_flag_is_one_per_family_and_absent_without_a_pin(self):
        base = {"role": "worker", "brief_path": "b", "cwd": "/w", "schema_path": "s"}
        argv = delegate.RunRequest(**base, only_family=["openai", "xai"]).to_argv("py", "r")
        self.assertEqual([argv[i + 1] for i, x in enumerate(argv) if x == "--only-family"], ["openai", "xai"])
        self.assertNotIn("--only-family", delegate.RunRequest(**base).to_argv("py", "r"))

    def test_the_words_name_the_pin_the_reason_and_that_no_other_family_runs(self):
        why = pin.stop_why("write", ["openai"], "only_family_unready", "codex out until 21:00")
        self.assertTrue(why.startswith("paused: no ready lane of the pinned writer family (openai) for write (only_family_unready)"))
        self.assertIn("no other family is used", why)
        self.assertIn("openai", pin.describe(["openai"]))
        self.assertIn("none", pin.describe([]))


if __name__ == "__main__":
    unittest.main()
