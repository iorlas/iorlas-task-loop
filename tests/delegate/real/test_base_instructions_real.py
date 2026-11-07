"""The prompt's repository instructions come from the base commit when a ref is given, whatever the work tree says now (tl-7i9k.58)."""
import os
import subprocess as sp
from pathlib import Path

import hermetic  # noqa: F401
from support.procsim import real_proc
from support.tmpdir import TemporaryDirectory

from delegate.app import launch

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env={**os.environ, **ENV}, check=True)
    return r.stdout.strip()


@real_proc("delegate: git reads the committed instruction files")
def test_the_base_text_replaces_the_work_trees_and_a_subfolder_is_walked():
    with TemporaryDirectory() as d:
        repo = Path(d)
        git(repo, "init", "-q")
        (repo / "AGENTS.md").write_text("BASE rules")
        (repo / "sub").mkdir()
        (repo / "sub" / "CLAUDE.md").write_text("BASE sub rules")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        (repo / "AGENTS.md").write_text("CANDIDATE rules")  # an approved-but-not-base edit, in the work tree only
        (repo / "sub" / "CLAUDE.md").write_text("CANDIDATE sub rules")

        text = launch.repo_instruction_text(str(repo / "sub"), ref=base)
        assert "BASE rules" in text and "BASE sub rules" in text
        assert "CANDIDATE" not in text
        assert "CANDIDATE rules" in launch.repo_instruction_text(str(repo / "sub"))  # no ref: the work tree, as before
