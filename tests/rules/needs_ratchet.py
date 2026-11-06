"""The capability ratchet's counter: what each test declares it needs that a logic test does not have (CLAUDE.md, Build & Test).

A declaration is `@needs(capability, reason)`, or the older `@real_proc(reason)` (capability process) and `@real_git(reason)` (git).
Counted per capability and reason in a test file. Judged on the change (ratchet_change.py): a rise over the files the change touches fails
unless a commit says `Ratchet-allow: needs +N reason`; a reason that is new must be said once, in words: the same line on many tests
explains none of them."""
import ast
from pathlib import Path

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


def file_counts(rel: str, tree: ast.Module) -> dict[str, int]:
    """{"capability: reason": n} of one test file; empty for any other file."""
    if not rel.startswith("tests/") or not Path(rel).name.startswith("test_"):
        return {}
    out: dict[str, int] = {}
    for cap, reason in declared(tree):
        key = f"{cap}: {reason}"
        out[key] = out.get(key, 0) + 1
    return out


def weak_new(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """New reasons (keys the touched files did not hold before) too short to explain a test, or said on more than one test."""
    bad = []
    for key, n in sorted(after.items()):
        if key in before:
            continue
        reason = key.split(": ", 1)[1]
        if reason != DYNAMIC and len(reason.split()) < MIN_WORDS:
            bad.append(f"{key!r} is under {MIN_WORDS} words")
        if n > 1:
            bad.append(f"{key!r} is on {n} tests")
    return bad
