"""app/doctor/profiles.py through the Git port, over the gitsim (no process): the profile on the base ref, else the working tree's."""
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from support import gitsim

from taskloop.adapters.git import RealGit
from taskloop.app.doctor import profiles
from taskloop.contracts.env import snapshot

BAD = {"engine": {"checks": [{"id": "t", "cmd": "just test"}]}}


class ProfilesOnTheSim(unittest.TestCase):
    def setUp(self) -> None:
        gitsim.reset()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        sim = gitsim.Sim(self)
        sim.install(stack)
        self.addCleanup(sim.check)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        gitsim.new_world(self.home)
        self.wt = self.home / "wt"
        self.git = RealGit(snapshot())

    def commit_profile(self, profile: dict) -> None:
        (self.wt / profiles.FILE).write_text(json.dumps(profile))
        self.git.stage(str(self.wt), profiles.FILE)
        self.git.commit_staged(str(self.wt), "profile")
        self.git.push(str(self.wt), "origin", "HEAD:main")
        self.git.fetch(str(self.wt))

    def test_the_profile_is_read_from_the_commit_on_the_base_ref(self) -> None:
        self.commit_profile({"slots": {"count": 0}})
        text, src = profiles.source(self.git, self.wt)
        self.assertEqual(json.loads(text), {"slots": {"count": 0}})
        self.assertTrue(src.startswith("base "), src)

    def test_a_bad_committed_profile_is_a_red_row_naming_the_file(self) -> None:
        self.commit_profile(BAD)
        row = profiles.red_row(self.git, self.wt)
        self.assertTrue(row.startswith("RED "), row)
        self.assertIn(profiles.FILE, row)

    def test_a_base_without_the_file_is_no_profile_and_a_red_row_of_none(self) -> None:
        text, src = profiles.source(self.git, self.wt)
        self.assertEqual(text, "")
        self.assertTrue(src.startswith("base "), src)
        self.assertEqual(profiles.red_row(self.git, self.wt), "")


if __name__ == "__main__":
    unittest.main()
