"""`tl land-stack` arguments: an item is a PR number, a pull url or a branch; --bead and --supersede are keyed by the item text."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl_main

# isort: split
from taskloop.cli.land_stack import item_of, pairs


class Items(unittest.TestCase):
    def test_a_number_a_url_and_a_branch(self):
        self.assertEqual((item_of("12", {}, {}).pr, item_of("12", {}, {}).branch), (12, ""))
        self.assertEqual(item_of("https://github.com/o/r/pull/34/", {}, {}).pr, 34)
        b = item_of("task/x", {"task/x": "tl-1"}, {"task/x": "9"})
        self.assertEqual((b.branch, b.pr, b.bead, b.supersedes), ("task/x", 0, "tl-1", 9))

    def test_a_pair_without_a_value_is_refused(self):
        with self.assertRaises(SystemExit):
            pairs(["task/x"], "--bead")

    def test_the_verb_is_registered_and_has_help(self):
        r = tl_main("land-stack", "--help", cwd=".")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--supersede", r.stdout)


if __name__ == "__main__":
    unittest.main()
