import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "dev", "check_move.py")

FUNC = 'def area(self, w, h):\n    """Rectangle area."""\n    return self.scale * w * h\n'


class CheckMove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.git("init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *a):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(("git", "-c", "commit.gpgsign=false") + a, cwd=self.d, env=env,
                              check=True, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()

    def write(self, name, text):
        with open(os.path.join(self.d, name), "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run_tool(self, base, head, *extra):
        r = subprocess.run([sys.executable, TOOL, base, head] + list(extra), cwd=self.d,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
        return r.returncode, r.stdout

    def base(self, func=FUNC):
        self.write("a.py", "import os\n\n" + func + "\ndef keep():\n    return 1\n")
        return self.commit("base")

    def move(self, new_func):
        self.write("a.py", "import os\n\ndef keep():\n    return 1\n")
        self.write("b.py", new_func)
        return self.commit("move")

    def test_move_passes(self):
        b = self.base()
        rc, out = self.run_tool(b, self.move(FUNC))
        self.assertEqual(rc, 0, out)
        self.assertIn("a.py:area", out)

    def test_planted_edit_fails_and_names(self):
        b = self.base()
        rc, out = self.run_tool(b, self.move(FUNC.replace("w * h", "w * h + 1")))
        self.assertNotEqual(rc, 0)
        self.assertIn("FAIL", out)
        self.assertIn("area", out)

    def test_deleted_without_destination_fails(self):
        b = self.base()
        self.write("a.py", "import os\n\ndef keep():\n    return 1\n")
        rc, out = self.run_tool(b, self.commit("del"))
        self.assertNotEqual(rc, 0)
        self.assertIn("area", out)

    def test_rename_only_with_flag(self):
        b = self.base()
        h = self.move(FUNC.replace("self", "eng"))
        rc, out = self.run_tool(b, h)
        self.assertNotEqual(rc, 0, out)
        rc, out = self.run_tool(b, h, "--rename", "self=eng")
        self.assertEqual(rc, 0, out)

    def test_class_move_passes(self):
        cls = 'class K:\n    """doc"""\n    def m(self):\n        return 2\n'
        b = self.base(cls)
        rc, out = self.run_tool(b, self.move(cls))
        self.assertEqual(rc, 0, out)

    def edit_in_place(self):
        b = self.base()
        self.write("a.py", "import os\n\n" + FUNC.replace("w * h", "w + h") + "\ndef keep():\n    return 1\n")
        return b, self.commit("edit")

    def test_in_place_edit_fails_and_names(self):
        b, h = self.edit_in_place()
        rc, out = self.run_tool(b, h)
        self.assertNotEqual(rc, 0)
        self.assertIn("a.py:area changed in place", out)

    def test_allow_edit_passes_in_place(self):
        b, h = self.edit_in_place()
        rc, out = self.run_tool(b, h, "--allow-edit", "a.py:area")
        self.assertEqual(rc, 0, out)

    def test_unaccounted_new_function_fails_then_allowed(self):
        b = self.base()
        self.write("a.py", open(os.path.join(self.d, "a.py")).read() + "\ndef extra():\n    return 3\n")
        h = self.commit("add")
        rc, out = self.run_tool(b, h)
        self.assertNotEqual(rc, 0)
        self.assertIn("a.py:extra added", out)
        rc, out = self.run_tool(b, h, "--allow-edit", "a.py:extra")
        self.assertEqual(rc, 0, out)

    def test_top_level_statement_change_fails(self):
        b = self.base()
        self.write("a.py", open(os.path.join(self.d, "a.py")).read() + "\nLIMIT = 5\n")
        rc, out = self.run_tool(b, self.commit("const"))
        self.assertNotEqual(rc, 0)
        self.assertIn("a.py:<module>", out)

    def test_import_and_comment_only_passes(self):
        b = self.base()
        self.write("a.py", "# note\nimport os\nimport sys\n\n\n" + FUNC + "\n\ndef keep():\n    return 1\n")
        rc, out = self.run_tool(b, self.commit("imports"))
        self.assertEqual(rc, 0, out)

    def test_real_trim_commit(self):
        # Runs against this repo's history; skipped if history is shallow.
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", "skills/task-loop/trim.py"],
                           cwd=ROOT, stdout=subprocess.PIPE, universal_newlines=True)
        sha = r.stdout.split()[-1] if r.stdout.split() else ""
        if not sha:
            self.skipTest("trim.py history unavailable")

        def run(*extra):
            return subprocess.run([sys.executable, TOOL, sha + "~1", sha] + list(extra), cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        r = run()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("engine.py:Engine.fix changed in place", r.stdout)
        allow = []
        for line in r.stdout.splitlines():
            if line.startswith("FAIL: "):
                allow += ["--allow-edit", line[6:].split(" ")[0]]
        r = run(*allow)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
