"""The capability ratchet's counter: what each test declares it needs that a logic test does not have (CLAUDE.md, Build & Test).

A declaration is `@needs(capability, reason)`, or the older `@real_proc(reason)` (capability process) and `@real_git(reason)` (git).
Counted per capability and reason over every test file. `needs_baseline.json` holds today's counts; only an increase fails, and a reason
that is new must be said once, in words: the same line on many tests explains none of them. `PYTHONPATH=tests uv run python -m
rules.needs_ratchet --write` rewrites the baseline after a cleanup lowers a count."""
import ast
import json
import sys
from pathlib import Path

from rules.gate_rules import parsed

TESTS = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("needs_baseline.json")
LEGACY = {"real_proc": "process", "real_git": "git"}
DYNAMIC = "<not a literal>"
MIN_WORDS = 5


def literal(node: ast.expr | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else DYNAMIC


def declared(tree: ast.Module) -> list[tuple[str, str]]:
    """[(capability, reason)] for each decorator of a function or class in the file."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            name = getattr(deco.func, "id", None) or getattr(deco.func, "attr", None)
            if name == "needs" and len(deco.args) >= 2:
                found.append((literal(deco.args[0]), literal(deco.args[1])))
            elif name in LEGACY and deco.args:
                found.append((LEGACY[name], literal(deco.args[0])))
    return found


def count_tree(root: Path = TESTS) -> dict[str, dict[str, int]]:
    """{capability: {reason: n}} over the test files."""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("test_*.py")):
        _, tree = parsed(path)
        for cap, reason in declared(tree):
            row = out.setdefault(cap, {})
            row[reason] = row.get(reason, 0) + 1
    return out


def grown(now: dict[str, dict[str, int]], base: dict[str, dict[str, int]]) -> list[str]:
    """The (capability, reason) pairs above the baseline: the new declarations."""
    return [f"{cap}: {reason!r} {n} (baseline {base.get(cap, {}).get(reason, 0)})"
            for cap, row in sorted(now.items()) for reason, n in sorted(row.items()) if n > base.get(cap, {}).get(reason, 0)]


def weak_new(now: dict[str, dict[str, int]], base: dict[str, dict[str, int]]) -> list[str]:
    """New reasons (not in the baseline) too short to explain a test, or said on more than one test."""
    bad = []
    for cap, row in sorted(now.items()):
        for reason, n in sorted(row.items()):
            if reason in base.get(cap, {}):
                continue
            if reason != DYNAMIC and len(reason.split()) < MIN_WORDS:
                bad.append(f"{cap}: {reason!r} is under {MIN_WORDS} words")
            if n > 1:
                bad.append(f"{cap}: {reason!r} is on {n} tests")
    return bad


if __name__ == "__main__":
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(count_tree(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({c: sum(r.values()) for c, r in count_tree().items()}, indent=1, sort_keys=True))
