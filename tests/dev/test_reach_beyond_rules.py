"""Reach reports both total selection and selection beyond the rules, without git."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("reach", Path(__file__).resolve().parents[2] / "dev/reach.py")
assert SPEC is not None and SPEC.loader is not None
reach = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reach)


def test_report_excludes_always_run_rules(monkeypatch):
    rules = {"tests/rules/test_one.py", "tests/rules/test_two.py"}
    own = {"tests/run/test_one.py", "tests/run/test_two.py", "tests/run/test_three.py"}
    selections = {"small.py": rules | {min(own)}, "large.py": rules | own}
    repo = SimpleNamespace(trees=rules | own | selections.keys(), edges={})
    monkeypatch.setattr(reach, "Repo", lambda root: repo)
    monkeypatch.setattr(reach, "commit_files", lambda root, count: [{"small.py"}, {"large.py"}])
    monkeypatch.setattr(reach, "select", lambda repo, changed: list(selections[next(iter(changed))] if changed else rules))

    lines = reach.report(Path("unused"), 2).splitlines()

    assert lines[:3] == [
        "tests 5, commits measured 2",
        "selected per commit: median 4.0, mean 4, p90 5, max 5",
        "beyond the always-run tests/rules (2 files): median 2.0, mean 2, p90 3, max 3",
    ]
