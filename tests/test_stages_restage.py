"""tl-7y6.23: the run works on top of the base: before each stage after the first the branch is rebased when the base moved."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support.engine_case import CLEAN, PLAN, WRITE
from test_stages import StagesTest

HAS_G = te.shlex.join([sys.executable, "-c", "import os,sys; sys.exit(0 if os.path.exists('g.txt') else 1)"])
TWO = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g", files=["g.txt"], checks=[HAS_G], anchors=[])])


class Restage(StagesTest):
    def move_main(self, name="m.txt", text="main moved\n"):
        """A review answer that, as it passes, pushes a commit to origin/main (main moves while the run works)."""
        def answer(*_a):
            base = Path(self.tmp.name, "base-moves")
            if not base.exists():
                te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
            te.sh("git", "pull", "-q", "origin", "main", cwd=base)
            (base / name).write_text(text)
            te.sh("git", "add", "-A", cwd=base)
            te.sh("git", "commit", "-qm", "main moves", cwd=base)
            te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
            return CLEAN
        return answer

    @staticmethod
    def write_g(_s, _node, cwd, _resume):
        Path(cwd, "g.txt").write_text("g\n")
        return WRITE

    def test_main_moved_the_next_stage_runs_on_the_rebased_tree(self):
        seen = []

        def second(s, node, cwd, resume):
            seen.append(Path(cwd, "m.txt").exists())
            return self.write_g(s, node, cwd, resume)
        rc, _s = self.run_engine({"plan": [TWO], "write": [WRITE, second], "review": [self.move_main(), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(seen, [True])
        text = self.eng.log_path.read_text()
        self.assertIn("rebased the task branch onto the latest origin/main (1 commits behind) between stages", text)

    def test_main_did_not_move_no_rebase(self):
        rc, _s = self.run_engine({"plan": [TWO], "write": [WRITE, self.write_g], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("rebased the task branch", self.eng.log_path.read_text())

    @staticmethod
    def mine(_s, _node, cwd, _resume):
        Path(cwd, "a.txt").write_text("mine\n")
        return WRITE

    def test_a_conflict_between_stages_goes_to_the_fix_round(self):
        def fix(_s, _node, cwd, _resume):
            Path(cwd, "a.txt").write_text("merged\n")
            return WRITE
        rc, s = self.run_engine({"plan": [TWO], "write": [self.mine, fix, self.write_g],
                                 "review": [self.move_main("a.txt", "theirs\n"), CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("conflict", s.prompts[2])
        self.assertIn("fixed in place", self.eng.log_path.read_text())
        self.assertEqual(self.eng.git("show", "origin/main:a.txt"), "merged")

    def test_a_failed_fix_blocks_with_the_branch_kept(self):
        rc, _s = self.run_engine({"plan": [TWO], "write": [self.mine, WRITE, WRITE],
                                  "review": [self.move_main("a.txt", "theirs\n"), CLEAN, CLEAN]}, max_check_tries=1, max_rounds=1)
        self.assertNotEqual(rc, 0)
        self.assertIn("no longer fits", self.eng.log_path.read_text())
        self.assertEqual(self.eng.git("show", "task/t-1:a.txt"), "mine")  # the work is kept as it was
