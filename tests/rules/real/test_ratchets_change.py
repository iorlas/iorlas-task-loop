"""The effects, layer, temp and needs ratchets judge the change against its merge base with origin/main (tests/rules/ratchet_change.py):
nothing stored, so two PRs in different areas never share a file. The first test runs them on this very change;
the others build a small repo."""
import subprocess
import sys
from pathlib import Path

import pytest

from tltestkit.procsim import CAPABILITIES

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rules import effects_ratchet, layer_ratchet, needs_ratchet, ratchet_change, root_ratchet, temp_ratchet
from rules.gate_rules import ROOT

RATCHETS = {"effects": effects_ratchet.file_counts, "layer": layer_ratchet.file_counts, "temp": temp_ratchet.file_counts,
            "root": root_ratchet.file_counts}


def git(root, *argv):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *argv], capture_output=True, text=True, check=True)


def test_this_change_raises_no_ratchet():
    if ratchet_change.merge_base(ROOT) is None:
        pytest.skip("no origin/main to compare with")
    bad = {
        name: ratchet_change.problems(name, counter, ROOT, counter_at=root_ratchet.counter_for if name == "root" else None)
        for name, counter in RATCHETS.items()
    }
    bad["needs"] = needs_ratchet.problems(ROOT)
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
    (root / "src" / "new.py").write_text("import tempfile\nx = tempfile.mkdtemp()\n", encoding="utf-8")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == ["site: +1"]


def test_a_cleanup_and_a_move_pass(workdir):
    root = repo(workdir)
    (root / "src" / "old.py").rename(root / "src" / "moved.py")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []
    (root / "src" / "moved.py").write_text("x = 1\n", encoding="utf-8")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []


def test_a_commit_line_with_a_reason_allows_a_rise(workdir):
    root = repo(workdir)
    (root / "src" / "new.py").write_text("import tempfile\nx = tempfile.mkdtemp()\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "add\n\nRatchet-allow: temp +1 the git sandbox needs a real system temp dir")
    assert ratchet_change.problems("temp", temp_ratchet.file_counts, root) == []
    git(root, "commit", "-q", "--allow-empty", "-m", "more\n\nRatchet-allow: temp +1 no")
    base = ratchet_change.merge_base(root)
    assert base is not None and ratchet_change.allowed(root, base, "temp") == 1


def test_no_origin_main_means_no_judgement(workdir):
    git(workdir, "init", "-q", "-b", "main")
    assert ratchet_change.merge_base(workdir) is None
    assert ratchet_change.problems("root", root_ratchet.file_counts, workdir, counter_at=root_ratchet.counter_for) is None


def root_contract(*modules):
    return "[importlinter:contract:nobody-imports-a-root]\nforbidden_modules =\n" + "".join(f"    {m}\n" for m in modules)


def root_repo(workdir, monkeypatch):
    root = repo(workdir)
    monkeypatch.setattr(root_ratchet, "ROOT", root)
    (root / ".importlinter").write_text(root_contract("old", "keep"), encoding="utf-8")
    (root / "src/old.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")
    (root / "src/keep.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "roots")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def test_a_deleted_root_removed_from_the_contract_pays_down_sloc(workdir, monkeypatch):
    root = root_repo(workdir, monkeypatch)
    (root / ".importlinter").write_text(root_contract("keep"), encoding="utf-8")
    (root / "src/old.py").unlink()
    base = ratchet_change.merge_base(root)
    assert base is not None
    before, after = ratchet_change.net(root_ratchet.file_counts, root, base, ratchet_change.changed_py(root, base),
                                      counter_at=root_ratchet.counter_for)
    assert before.get("sloc", 0) == 4
    assert after.get("sloc", 0) == 0


def test_a_removed_root_pays_for_a_binding_elsewhere(workdir, monkeypatch):
    root = root_repo(workdir, monkeypatch)
    (root / ".importlinter").write_text(root_contract("keep"), encoding="utf-8")
    (root / "src/old.py").unlink()
    (root / "src/keep.py").write_text("x = 1\na = 2\nb = 3\nc = 4\n", encoding="utf-8")
    assert ratchet_change.problems("root", root_ratchet.file_counts, root, counter_at=root_ratchet.counter_for) == []


def test_a_new_root_in_the_contract_counts_as_a_rise(workdir, monkeypatch):
    root = root_repo(workdir, monkeypatch)
    (root / ".importlinter").write_text(root_contract("old", "keep", "new"), encoding="utf-8")
    (root / "src/new.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    assert ratchet_change.problems("root", root_ratchet.file_counts, root,
                                  counter_at=root_ratchet.counter_for) == ["sloc: +3"]


def needs_repo(workdir):
    root = repo(workdir)
    (root / "tests").mkdir()
    (root / "tests/test_sample.py").write_text(
        "@needs('process', 'the child process receives a signal')\ndef test_a(): pass\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base needs")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


@pytest.mark.parametrize(("source", "expected"), [
    ("@needs('process', 'a child exits after receiving termination')\ndef test_a(): pass\n", []),
    ("@needs('process', 'the child process receives a signal')\ndef test_a(): pass\n"
     "@needs('process', 'a child exits after receiving termination')\ndef test_b(): pass\n", ["process: +1"]),
    ("@needs('process', 'short reason')\ndef test_a(): pass\n", ["'process: short reason' is under 5 words"]),
    ("@needs('process', 'a child exits after receiving termination')\ndef test_a(): pass\n"
     "@needs('process', 'a child exits after receiving termination')\ndef test_b(): pass\n",
     ["process: +1", "'process: a child exits after receiving termination' is on 2 tests"]),
])
def test_needs_totals_and_new_reasons(workdir, source, expected):
    root = needs_repo(workdir)
    (root / "tests/test_sample.py").write_text(source, encoding="utf-8")
    assert needs_ratchet.problems(root) == expected


def effects_repo(workdir):
    root = repo(workdir)
    kernel = root / "packages/kernel/src/tlkernel"
    kernel.mkdir(parents=True)
    (kernel / "old.py").write_text("import sqlite3\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "old kernel effect")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root, kernel


def test_a_new_kernel_effect_fails_an_unchanged_old_one_does_not(workdir):
    root, kernel = effects_repo(workdir)
    assert ratchet_change.problems("effects", effects_ratchet.file_counts, root) == []
    (kernel / "new.py").write_text("import sqlite3\n", encoding="utf-8")
    assert ratchet_change.problems("effects", effects_ratchet.file_counts, root) == ["sqlite: +1"]


def test_kernel_str_replace_is_noise(workdir):
    root, kernel = effects_repo(workdir)
    (kernel / "new.py").write_text("value = 'a'.replace('a', 'b')\n", encoding="utf-8")
    assert ratchet_change.problems("effects", effects_ratchet.file_counts, root) == []


def test_moving_a_kernel_effect_is_net_zero(workdir):
    root, kernel = effects_repo(workdir)
    (kernel / "old.py").rename(kernel / "moved.py")
    assert ratchet_change.problems("effects", effects_ratchet.file_counts, root) == []
