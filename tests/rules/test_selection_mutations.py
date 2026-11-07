"""Seeded mutations prove the test selection (dev/affected.py): each one names a changed file, and the selection must hold the test that
would fail. A selector that misses one of these lets a break through `just test`. In process: the import graph of the checkout is read once
(affected.Repo) and every case asks it, so ten cases cost one parse of the tree, not ten runs of the script.
`main` is called once, on a one-file tree, for its wiring."""
import contextlib
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import affected  # noqa: E402

# (mutation, changed path, a test that fails because of it and must be selected)
MUTATIONS = {
    "a function body in a leaf module": ("src/taskloop/domain/beads/rules.py", "tests/loop/test_lint.py"),
    "a signature in contracts": ("packages/kernel/src/tlkernel/ids.py", "tests/contracts/test_wire.py"),
    "a testkit helper": ("packages/testkit/src/tltestkit/procsim.py", "tests/land/test_engine_land_1.py"),
    "the import-linter contracts": (".importlinter", "tests/rules/gate_rules.py"),
    "a constant in a vendored package": ("skills/task-loop/_vendor/any_clock/clock.py", "tests/land/test_push_timing.py"),
    "a script that tests run by path": ("skills/task-loop/tl.py", "tests/cli/test_tl.py"),
    "a contracts golden file": ("tests/contracts/golden/engine_log.jsonl", "tests/contracts/test_wire.py"),
    "a scoped HTML sink": ("packages/dash/src/tldash/static/index.html", "tests/rules/test_dash_xss.py"),
    "a changed test file": ("tests/loop/test_lint.py", "tests/loop/test_lint.py"),
    "pyproject.toml": ("pyproject.toml", "tests/release/test_manifest.py"),
}


@pytest.fixture(scope="module")
def repo():
    return affected.Repo(ROOT)


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_selection_holds_the_test_the_mutation_breaks(repo, name):
    path, expected = MUTATIONS[name]
    chosen = affected.select(repo, {path})
    assert expected in chosen, f"{name}: {path} changed, {expected} not selected ({len(chosen)} selected)"
    assert "tests/rules/gate_rules.py" in chosen  # the rules always run


def test_a_change_that_reaches_no_test_selects_the_rules_only(repo):
    chosen = affected.select(repo, {"NOTES.md"})
    assert chosen and all(p.startswith("tests/rules/") for p in chosen)


def test_every_record_module_selects_the_wire_test(repo):
    """The discovery rule's premise: the wire test asks every module of contracts for a sample, so a new one (the graph is read fresh
    each run) reaches it as every existing one does."""
    modules = [p for p in repo.trees
               if p.startswith("packages/kernel/src/tlkernel/") and p.count("/") == 4 and not p.endswith("__init__.py")]
    missed = [p for p in modules if "tests/contracts/test_wire.py" not in affected.select(repo, {p})]
    assert modules and missed == []


def test_main_prints_the_selection_of_the_given_paths(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert affected.main(["--root", str(tmp_path), "--changed", "tests/test_a.py"]) == 0
    assert out.getvalue().split() == ["tests/test_a.py"]


@pytest.mark.parametrize("path, policy", [
    ("unrelated.txt", "unrelated"),
    ("NOTES.md", "whole-tree"),
    ("justfile", "config"),
])
def test_rule_selection_policy(repo, path, policy):
    chosen = set(affected.select(repo, {path}))
    assert chosen >= affected.ALWAYS_RULES
    if policy == "unrelated":
        assert not chosen & affected.RULES_BY_PATH.keys()
    if policy == "config":
        assert affected.under(repo, "tests/rules") <= chosen


def test_unclassified_rule_defaults_to_always(tmp_path):
    rules = tmp_path / "tests/rules"
    rules.mkdir(parents=True)
    (rules / "test_new.py").write_text("def test_new(): pass\n")
    assert "tests/rules/test_new.py" in affected.select(affected.Repo(tmp_path), {"unrelated.txt"})


def test_lander_keeps_rules_reached_through_the_gate_helper(repo):
    # gate_rules discovers taskloop modules and is imported by these bounded checks.
    chosen = set(affected.select(repo, {"src/taskloop/app/land/lander.py"}))
    assert chosen & affected.RULES_BY_PATH.keys() == {
        "tests/rules/test_dash_engine_sql.py", "tests/rules/test_kernel_has_no_effects.py",
        "tests/rules/test_ratchets.py", "tests/rules/test_round_handoffs.py",
    }
