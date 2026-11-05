"""Seeded mutations prove the test selection (dev/affected.py): each one changes a file in a temp copy of the tree, and the selection the
real script prints must hold the test that would fail. A selector that misses one of these lets a break through `just test`."""
import shutil
import sys
from pathlib import Path

import pytest
from support.checked import run_checked

ROOT = Path(__file__).resolve().parents[3]
LIMIT_S = 45.0  # each case starts the selector on a fresh copy of the tree (about 10 s on a loaded Mac)
COPIED = ("src", "tests", "dev", "skills/task-loop", ".importlinter", "pyproject.toml")
NEW_RECORD = '''"""A record type nobody wrote a sample for."""
from taskloop.contracts.wire import Rec


class Unsampled(Rec):
    value: int
'''

# (mutation, changed paths, a test that fails because of it and must be selected)
MUTATIONS = {
    "a function body in a leaf module": ("src/taskloop/domain/beads/rules.py", "tests/loop/test_lint.py"),
    "a signature in contracts": ("src/taskloop/contracts/ids.py", "tests/contracts/test_wire.py"),
    "a new record type with no sample": ("src/taskloop/contracts/zz_unsampled.py", "tests/contracts/test_wire.py"),
    "a test support helper": ("tests/support/procsim.py", "tests/land/test_pr_land.py"),
    "the import-linter contracts": (".importlinter", "tests/rules/gate_rules.py"),
    "a constant in a vendored package": ("skills/task-loop/_vendor/any_clock/clock.py", "tests/land/test_push_timing.py"),
    "a script that tests run by path": ("skills/task-loop/tl.py", "tests/cli/test_tl.py"),
    "a contracts golden file": ("tests/contracts/golden/engine_log.jsonl", "tests/contracts/test_wire.py"),
    "a changed test file": ("tests/loop/test_lint.py", "tests/loop/test_lint.py"),
    "pyproject.toml": ("pyproject.toml", "tests/release/test_manifest.py"),
}


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """A copy of the checkout's code and tests; the mutations are applied to it, never to the real tree."""
    copy = tmp_path_factory.mktemp("selection")
    for name in COPIED:
        src = ROOT / name
        dst = copy / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".venv"))
        else:
            shutil.copy2(src, dst)
    return copy


def mutate(tree, path):
    target = tree / path
    if path.endswith("zz_unsampled.py"):
        target.write_text(NEW_RECORD, encoding="utf-8")
    else:
        with target.open("a", encoding="utf-8") as f:
            f.write("\n" if path.endswith(".jsonl") else "\n# mutated\n")


def selected(tree, path):
    ran = run_checked([sys.executable, str(tree / "dev" / "affected.py"), "--root", str(tree), "--changed", path], None, text=True)
    return set(ran.stdout.split())


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_selection_holds_the_test_the_mutation_breaks(tree, name):
    path, expected = MUTATIONS[name]
    mutate(tree, path)
    chosen = selected(tree, path)
    assert expected in chosen, f"{name}: {path} changed, {expected} not selected ({len(chosen)} selected)"
    assert "tests/rules/gate_rules.py" in chosen  # the rules always run


def test_a_change_that_reaches_no_test_selects_the_rules_only(tree):
    (tree / "NOTES.md").write_text("notes\n", encoding="utf-8")
    chosen = selected(tree, "NOTES.md")
    assert chosen and all(p.startswith("tests/rules/") for p in chosen)
