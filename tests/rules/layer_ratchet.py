"""The test-layer ratchet's counter: what a test file holds that its layer does not allow (CLAUDE.md, Test layers).

Two offenders in a file outside `real/`, `e2e/` and `live/`: a `@real_proc` / `@real_git` mark (a real process or git inside a test that
sits among the unit tests) and a `time.sleep(` call (a real wait; inject the clock). Judged on the change (ratchet_change.py): a rise
in either, over the files the change touches, fails unless a commit says `Ratchet-allow: layer +N reason`."""
import ast
from pathlib import Path

MARKS = frozenset({"real_proc", "real_git"})
OWN_KINDS = frozenset({"real", "e2e", "live", "fixtures"})


def offenders(tree: ast.Module) -> dict[str, int]:
    found = {"real_mark": 0, "sleep": 0}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in node.decorator_list:
                fn = deco.func if isinstance(deco, ast.Call) else deco
                found["real_mark"] += (getattr(fn, "id", None) or getattr(fn, "attr", None)) in MARKS
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sleep":
            found["sleep"] += getattr(node.func.value, "id", "") == "time"
    return found


def file_counts(rel: str, tree: ast.Module) -> dict[str, int]:
    """{offender: n} of one test file outside real/, e2e/, live/ and the support code; empty for any other file."""
    parts = Path(rel).parts
    if parts[0] != "tests" or not parts[-1].startswith("test_") or OWN_KINDS & set(parts[:-1]):
        return {}
    return {kind: n for kind, n in offenders(tree).items() if n}
