"""The layer, temp and needs ratchets judge the change against its merge base with origin/main (tests/rules/ratchet_change.py): nothing
stored, so two PRs in different areas never share a file. The first test runs them on this very change; the others build a small repo."""
import subprocess
import sys
from pathlib import Path

import pytest
from support.procsim import CAPABILITIES

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from rules import layer_ratchet, needs_ratchet, ratchet_change, temp_ratchet
from rules.gate_rules import ROOT

RATCHETS = {"layer": layer_ratchet.file_counts, "temp": temp_ratchet.file_counts, "needs": needs_ratchet.file_counts}


def git(root, *argv):
    subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, check=True)


def test_this_change_raises_no_ratchet():
    if ratchet_change.merge_base(ROOT) is None:
        pytest.skip("no origin/main to compare with")
    bad = {name: ratchet_change.problems(name, counter, ROOT) for name, counter in RATCHETS.items()}
    assert {k: v for k, v in bad.items() if v} == {}, "fix it, or say it in a commit: `Ratchet-allow: <name> +N <reason in words>`"


def test_every_capability_a_touched_test_declares_is_known(workdir):
    base = ratchet_change.merge_base(ROOT)
    if base is None:
        pytest.skip("no origin/main to compare with")
    _, after = ratchet_change.net(needs_ratchet.file_counts, ROOT, base, ratchet_change.changed_py(ROOT, base))
    assert {key.split(": ")[0] for key in after} <= CAPABILITIES


def repo(workdir):
    git(workdir, "init", "-q", "-b", "main")
    (workdir / "src").mkdir()
    (workdir / "src" / "old.py").write_text("import tempfile\n", encoding="utf-8")
    git(workdir, "add", "-A")
    git(workdir, "commit", "-qm", "base")
    git(workdir, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(workdir, "checkout", "-qb", "change")
    return workdir


def test_a_new_temp_site_fails_an_old_one_does_not(workdir):
    root = repo(workdir)
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []
    (root / "src" / "new.py").write_text("import tempfile\nx = mkdtemp()\n", encoding="utf-8")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == ["site: +1"]


def test_a_cleanup_and_a_move_pass(workdir):
    root = repo(workdir)
    (root / "src" / "old.py").rename(root / "src" / "moved.py")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []
    (root / "src" / "moved.py").write_text("x = 1\n", encoding="utf-8")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []


def test_a_commit_line_with_a_reason_allows_a_rise(workdir):
    root = repo(workdir)
    (root / "src" / "new.py").write_text("import tempfile\nx = mkdtemp()\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "add\n\nRatchet-allow: temp +1 the git sandbox needs a real system temp dir")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []
    git(root, "commit", "-q", "--allow-empty", "-m", "more\n\nRatchet-allow: temp +1 no")
    base = ratchet_change.merge_base(root)
    assert base is not None and ratchet_change.allowed(root, base, "temp") == 1


def test_no_origin_main_means_no_judgement(workdir):
    git(workdir, "init", "-q", "-b", "main")
    assert ratchet_change.merge_base(workdir) is None
