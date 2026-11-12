"""What a land changes in the gate (tl-8bh9.14.42 and .43): `gate_of` over a semantic Git fake for each kind of fact (a
configuration file by shape, a deleted, rewritten or skipped test, a changed check argv), and the land over `land_bench`
refusing such an S, naming each fact, until the person passes `--accept-gate-changes`."""

import json
from pathlib import Path

import pytest
from git_porcelain import Recorded
from git_porcelain.testing import FakeRemote, FakeRepo
from land_bench import PROFILE, LandBench, bench

from taskloop.land import Landed
from taskloop.land_gate import ACCEPT, Gate, configuration, gate_of
from taskloop.land_push import Origin
from taskloop.land_render import landed_lines
from taskloop.land_summary import LandSummary, gate_lines, lines
from taskloop.operations import Failed

TESTS = "def test_a() -> None:\n    assert 1 == 1\n\n\ndef test_b() -> None:\n    assert 2 == 2\n    assert 3 == 3\n"
BASE = {".task-loop.json": json.dumps(PROFILE), "ruff.toml": "[lint]\nselect = ['E']\n", "tests/test_a.py": TESTS,
        "src/a.py": "A = 1\n"}


class Files:
    """The profile port over the repository's own objects: the file at the commit."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    def blob(self, commit: str, path: str) -> bytes | None:
        tree = self.repo.tree(commit)
        return None if tree is None else tree.read(path)


def landed(tmp_path: Path, change: dict[str, str | None]) -> Gate:
    """O is a commit of `BASE`; S is O with `change` applied (None deletes the file)."""
    remote = FakeRemote("https://example.invalid/repo.git")
    o = remote.advance("main", dict(BASE), "base")
    repo = FakeRepo.clone(remote, tmp_path / "main")
    root = repo.worktree(repo.identity().root)
    root.checkout_new("task/t")
    for path, text in change.items():
        root.write_file(path, text) if text is not None else root.remove_file(path)
    made = root.record("the task", paths="all")
    assert isinstance(made, Recorded)
    found = gate_of(Origin(repo, tmp_path / "main"), Files(repo), o, made.sha)
    assert isinstance(found, Gate), found
    return found


@pytest.mark.parametrize(("path", "named", "expected"), [
    ("ruff.toml", frozenset[str](), True), ("pyrefly.toml", frozenset[str](), True), ("justfile", frozenset[str](), True),
    (".importlinter", frozenset[str](), True), ("uv.lock", frozenset[str](), True), ("deep/conftest.py", frozenset[str](), True),
    ("scripts/setup.sh", frozenset({"scripts/setup.sh"}), True), ("README.md", frozenset[str](), False),
    ("src/a.py", frozenset[str](), False), ("src/ruff.toml", frozenset[str](), True), ("tests/pytest.ini", frozenset[str](), True),
    ("tox.cfg", frozenset[str](), True),
    ("docs/data.json", frozenset[str](), False), ("tests/rules/test_policy.py", frozenset[str](), False),
])
def test_a_configuration_file_is_a_root_file_a_toml_ini_or_cfg_at_any_depth_a_conftest_or_one_a_check_names(
    path: str, named: frozenset[str], expected: bool
) -> None:
    assert configuration(path, named) is expected


def test_a_replaced_tool_configuration_is_flagged_with_the_diffstat_of_every_changed_file(tmp_path: Path) -> None:
    gate = landed(tmp_path, {"ruff.toml": "[lint]\nselect = []\n", "src/b.py": "B = 1\n"})
    assert gate.configs == ("ruff.toml",) and gate.decisive and gate.weakened == ()
    assert [(each.path, each.kind) for each in gate.changes] == [("ruff.toml", "M"), ("src/b.py", "A")]
    text = gate_lines(gate)
    assert text[0] == "Files changed: 2 (+2 -1)" and "  M ruff.toml +1 -1" in text and "Configuration changed: ruff.toml" in text
    assert any(line.startswith(f"These change what decides a pass: rerun `tl step land` with {ACCEPT}") for line in text)


@pytest.mark.parametrize(("change", "why"), [
    ({"tests/test_a.py": None}, "deleted"),
    ({"tests/test_a.py": "def test_a() -> None:\n    assert True\n"}, "tests 2 -> 1"),
    ({"tests/test_a.py": TESTS.replace("assert 3 == 3\n", "")}, "assertions 3 -> 2"),
    ({"tests/test_a.py": "import pytest\n\npytestmark = pytest.mark.skip\n" + TESTS}, "skip, xfail or noqa markers 0 -> 1"),
    ({"tests/test_a.py": "from pytest import skip\n\n\ndef test_a() -> None:\n    skip()\n    assert 1 == 1\n\n\ndef test_b() -> None:\n"
                         "    assert 2 == 2\n    assert 3 == 3\n"}, "skip, xfail or noqa markers 0 -> 1"),
    ({"tests/test_a.py": "# ruff: noqa\n" + TESTS}, "skip, xfail or noqa markers 0 -> 1"),
    ({"tests/test_a.py": "def test_a(:\n"}, "does not parse"),
], ids=["deleted", "rewritten", "fewer_assertions", "skip_marker", "bare_skip_call", "file_noqa", "unparseable"])
def test_a_deleted_rewritten_skipped_or_unreadable_test_is_flagged(tmp_path: Path, change: dict[str, str | None], why: str) -> None:
    gate = landed(tmp_path, change)
    assert [(each.path, each.why) for each in gate.weakened] == [("tests/test_a.py", why)] and gate.decisive
    assert f"Test weakened: tests/test_a.py: {why}" in gate_lines(gate)


def test_added_tests_and_ordinary_source_changes_are_listed_but_decide_nothing(tmp_path: Path) -> None:
    gate = landed(tmp_path, {"src/a.py": "A = 2\n", "tests/test_b.py": TESTS, "tests/test_a.py": TESTS + "\n\ndef test_c() -> None:\n"
                             "    assert 4 == 4\n"})
    assert not gate.decisive and len(gate.changes) == 3 and gate.checks == () and gate.setup is None and gate.required is None


@pytest.mark.parametrize("element", ["./src/a.py", "src/", "src", ".", "..", "/abs/src/a.py"],
                         ids=["dot_slash", "folder_slash", "folder", "dot", "dotdot", "absolute"])
def test_a_file_a_check_argv_names_is_configuration_in_each_spelling_and_only_the_naming_ones(tmp_path: Path, element: str) -> None:
    """`_named` must not be silently empty: a changed source file is configuration exactly when an argv names it."""
    profile = {**PROFILE, "checks": [{"name": "check", "argv": ["python", element], "timeout": 60},
                                     {"name": "test", "argv": ["just", "test"], "timeout": 60}]}
    gate = landed(tmp_path, {".task-loop.json": json.dumps(profile), "src/a.py": "A = 2\n"})
    assert ("src/a.py" in gate.configs) is (element in ("./src/a.py", "src/", "src"))


def test_a_changed_check_argv_setup_and_required_list_are_each_a_fact(tmp_path: Path) -> None:
    profile = {"setup": [["just", "setup"]], "required": ["check"], "checks": [
        {"name": "check", "argv": ["true"], "timeout": 600}, {"name": "test", "argv": ["just", "test"], "timeout": 600}]}
    gate = landed(tmp_path, {".task-loop.json": json.dumps(profile)})
    assert [(each.name, each.at_x.argv if each.at_x else None) for each in gate.checks] == [("check", ("true",))]
    assert gate.setup == ((("just", "bootstrap"),), (("just", "setup"),)) and gate.required == (("check", "test"), ("check",))
    assert gate.configs == (".task-loop.json",)
    text = gate_lines(gate)
    assert "Check changed: check: just check (600 s) -> true (600 s)" in text and "Setup changed: just bootstrap -> just setup" in text
    assert "Required changed: check, test -> check" in text


@pytest.fixture
def hollowed(tmp_path: Path) -> LandBench:
    return bench(tmp_path, {"ruff.toml": "[lint]\nselect = []\n", "src/x.py": "X = 1\n"})


def test_a_land_that_changes_a_tool_configuration_is_refused_naming_it_until_accepted(hollowed: LandBench) -> None:
    b = hollowed
    found = b.land()
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", "gate_changed")
    assert "Configuration changed: ruff.toml" in found.detail and "  A ruff.toml +2 -0" in found.detail
    assert "Files changed: 2" in found.detail and b.rows() == () and b.repo.pushes == 0 and b.origin_main() == b.base
    again = b.land(accept=True)
    assert isinstance(again, Landed) and again.how == "pushed" and b.origin_main() == again.row.commit and b.repo.pushes == 1
    assert again.gate is not None and again.gate.configs == ("ruff.toml",)
    shown = landed_lines(again)  # the accepted land's plain output carries the facts (.14.43)
    assert "Gate changes accepted:" in shown and "Configuration changed: ruff.toml" in shown and "  A ruff.toml +2 -0" in shown


def test_a_land_that_changes_a_check_argv_is_refused_and_a_land_changing_nothing_of_it_lands_as_before(tmp_path: Path) -> None:
    profile = {"setup": [["just", "bootstrap"]], "required": ["check", "test"], "checks": [
        {"name": "check", "argv": ["true"], "timeout": 600}, {"name": "test", "argv": ["true"], "timeout": 600}]}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    b = bench(tmp_path / "a", {".task-loop.json": json.dumps(profile)})
    found = b.land()
    assert isinstance(found, Failed) and found.reason == "gate_changed"
    assert "Check changed: check: just check (600 s) -> true (600 s)" in found.detail and "Check changed: test:" in found.detail
    assert b.rows() == () and b.repo.pushes == 0
    plain = bench(tmp_path / "b")
    assert isinstance(plain.land(), Landed)


def test_the_summary_lists_the_same_facts_the_refusal_names(hollowed: LandBench) -> None:
    summary = hollowed.land("summary")
    refused = hollowed.land()
    assert isinstance(summary, LandSummary) and isinstance(refused, Failed)
    assert all(line in lines(summary) for line in refused.detail.splitlines()[1:])


def test_a_land_changing_nothing_in_the_gate_prints_no_gate_lines_even_with_the_flag(tmp_path: Path) -> None:
    found = bench(tmp_path).land(accept=True)
    assert isinstance(found, Landed) and found.gate is None and "Gate changes accepted:" not in landed_lines(found)


def test_a_refused_profile_names_whose_it_is(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    o = remote.advance("main", {".task-loop.json": "not json"}, "base")
    repo = FakeRepo.clone(remote, tmp_path / "main")
    root = repo.worktree(repo.identity().root)
    root.checkout_new("task/t")
    root.write_file(".task-loop.json", json.dumps(PROFILE))
    made = root.record("fix it", paths="all")
    assert isinstance(made, Recorded)
    found = gate_of(Origin(repo, tmp_path / "main"), Files(repo), o, made.sha)
    assert isinstance(found, Failed) and found.reason == "profile" and found.detail.startswith(f"The profile at origin main ({o})")
