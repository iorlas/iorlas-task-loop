"""Exercise the closure change ratchet on this checkout and on a small real git repo."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from rules import closure_ratchet
from rules.gate_rules import ROOT


def git(root, *argv):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *argv],
                   capture_output=True, text=True, check=True)


def repo(workdir):
    git(workdir, "init", "-q", "-b", "main")
    for stage in ("first", "second"):
        folder = workdir / "src" / "taskloop" / "app" / stage
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text("", encoding="utf-8")
    git(workdir, "add", "-A")
    git(workdir, "commit", "-qm", "base")
    git(workdir, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(workdir, "checkout", "-qb", "change")
    return workdir


def test_this_change_raises_no_stage_closure():
    bad = closure_ratchet.problems(ROOT)
    if bad is None:
        pytest.skip("no origin/main to compare with")
    assert bad == [], "fix it, or commit `Ratchet-allow: closure +N <reason in words>`"


def test_a_stage_growth_fails_and_a_commit_allowance_passes(workdir):
    root = repo(workdir)
    assert closure_ratchet.problems(root) == []
    source = root / "src" / "taskloop"
    (source / "new.py").write_text("", encoding="utf-8")
    (source / "app" / "first" / "__init__.py").write_text("import taskloop.new\n", encoding="utf-8")
    assert closure_ratchet.problems(root) == ["first: +1 files in the forward closure"]
    git(root, "add", "-A")
    git(root, "commit", "-qm", "grow\n\nRatchet-allow: closure +1 one more file for the demo")
    assert closure_ratchet.problems(root) == []
