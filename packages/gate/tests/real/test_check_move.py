"""dev/check_move.py: a pure move passes; a planted edit or a deletion without a destination fails."""
import contextlib
import importlib.util
import io
import os
import subprocess
from pathlib import Path

import pytest
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory

ROOT = str(Path(__file__).resolve().parents[4])
TOOL = os.path.join(ROOT, "dev", "check_move.py")

spec = importlib.util.spec_from_file_location("check_move", TOOL)
check_move = importlib.util.module_from_spec(must(spec))
must(must(spec).loader).exec_module(check_move)


def in_process(cwd, *argv):
    """check_move.main(argv) from `cwd` in this process -> (exit code, stdout and stderr)."""
    out = io.StringIO()
    with contextlib.chdir(cwd), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        return check_move.main(list(argv)), out.getvalue()


FUNC = 'def area(self, w, h):\n    """Rectangle area."""\n    return self.scale * w * h\n'


class CheckMove(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.d = self.tmp.name
        self.git("init", "-q")

    def teardown_method(self):
        self.tmp.cleanup()

    def git(self, *a):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(("git", "-c", "commit.gpgsign=false", *a), cwd=self.d, env=env,
                              check=True, stdout=subprocess.PIPE,
                              text=True).stdout.strip()

    def read(self, name):
        with open(os.path.join(self.d, name)) as f:
            return f.read()

    def write(self, name, text):
        with open(os.path.join(self.d, name), "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run_tool(self, base, head, *extra):
        return in_process(self.d, base, head, *extra)

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
        assert rc == 0, out
        assert "a.py:area" in out

    def test_planted_edit_fails_and_names(self):
        b = self.base()
        rc, out = self.run_tool(b, self.move(FUNC.replace("w * h", "w * h + 1")))
        assert rc != 0
        assert "FAIL" in out
        assert "area" in out

    def test_the_script_exits_1_naming_the_failure_and_0_for_a_move(self):
        b = self.base()
        rc, out = self.run_tool(b, self.move(FUNC.replace("w * h", "w * h + 1")))
        assert rc == 1
        assert "FAIL: a.py:area" in out
        rc, out = self.run_tool(b, self.move(FUNC))
        assert rc == 0, out

    def test_deleted_without_destination_fails(self):
        b = self.base()
        self.write("a.py", "import os\n\ndef keep():\n    return 1\n")
        rc, out = self.run_tool(b, self.commit("del"))
        assert rc != 0
        assert "area" in out

    def test_rename_only_with_flag(self):
        b = self.base()
        h = self.move(FUNC.replace("self", "eng"))
        rc, out = self.run_tool(b, h)
        assert rc != 0, out
        rc, out = self.run_tool(b, h, "--rename", "self=eng")
        assert rc == 0, out

    def test_class_move_passes(self):
        cls = 'class K:\n    """doc"""\n    def m(self):\n        return 2\n'
        b = self.base(cls)
        rc, out = self.run_tool(b, self.move(cls))
        assert rc == 0, out

    def edit_in_place(self):
        b = self.base()
        self.write("a.py", "import os\n\n" + FUNC.replace("w * h", "w + h") + "\ndef keep():\n    return 1\n")
        return b, self.commit("edit")

    def test_in_place_edit_fails_and_names(self):
        b, h = self.edit_in_place()
        rc, out = self.run_tool(b, h)
        assert rc != 0
        assert "a.py:area changed in place" in out

    def test_allow_edit_passes_in_place(self):
        b, h = self.edit_in_place()
        rc, out = self.run_tool(b, h, "--allow-edit", "a.py:area")
        assert rc == 0, out

    def test_unaccounted_new_function_fails_then_allowed(self):
        b = self.base()
        self.write("a.py", self.read("a.py") + "\ndef extra():\n    return 3\n")
        h = self.commit("add")
        rc, out = self.run_tool(b, h)
        assert rc != 0
        assert "a.py:extra added" in out
        rc, out = self.run_tool(b, h, "--allow-edit", "a.py:extra")
        assert rc == 0, out

    def test_top_level_statement_change_fails(self):
        b = self.base()
        self.write("a.py", self.read("a.py") + "\nLIMIT = 5\n")
        rc, out = self.run_tool(b, self.commit("const"))
        assert rc != 0
        assert "a.py:<module>" in out

    def test_import_and_comment_only_passes(self):
        b = self.base()
        self.write("a.py", "# note\nimport os\nimport sys\n\n\n" + FUNC + "\n\ndef keep():\n    return 1\n")
        rc, out = self.run_tool(b, self.commit("imports"))
        assert rc == 0, out

    def test_real_trim_commit(self):
        # Runs against this repo's history; skipped if history is shallow.
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", "skills/task-loop/trim.py"],
                           cwd=ROOT, stdout=subprocess.PIPE, text=True, check=False)
        sha = r.stdout.split()[-1] if r.stdout.split() else ""
        if not sha:
            pytest.skip("trim.py history unavailable")

        def run(*extra):
            return in_process(ROOT, sha + "~1", sha, *extra)
        rc, out = run()
        assert rc != 0, out
        assert "engine.py:Engine.fix changed in place" in out
        allow = []
        for line in out.splitlines():
            if line.startswith("FAIL: "):
                allow += ["--allow-edit", line[6:].split(" ")[0]]
        rc, out = run(*allow)
        assert rc == 0, out
