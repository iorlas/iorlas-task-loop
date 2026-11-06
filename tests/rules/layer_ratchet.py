"""The test-layer ratchet's counter: what each tests/ directory holds that its layer does not allow (CLAUDE.md, Test layers).

Two offenders, counted per directory outside `real/`, `e2e/` and `live/`: a `@real_proc` / `@real_git` mark (a real process or git
inside a test that sits among the unit tests) and a `time.sleep(` call (a real wait; inject the clock). `layer_baseline.json` holds
today's counts; `PYTHONPATH=tests uv run python -m rules.layer_ratchet --write` rewrites it after a cleanup lowers one."""
import ast
import json
import sys
from pathlib import Path

from rules.gate_rules import parsed

TESTS = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("layer_baseline.json")
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


def count_tree(root: Path = TESTS) -> dict[str, dict[str, int]]:
    """{directory: {offender: n}} for the directories that hold any; a test file outside real/, e2e/, live/ and support code."""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("test_*.py")):
        parts = path.relative_to(root).parts
        if OWN_KINDS & set(parts[:-1]):
            continue
        _, tree = parsed(path)
        for kind, n in offenders(tree).items():
            if n:
                row = out.setdefault("/".join(parts[:-1]) or ".", {})
                row[kind] = row.get(kind, 0) + n
    return out


def grown(now: dict[str, dict[str, int]], base: dict[str, dict[str, int]]) -> list[str]:
    """The directories whose count is above the baseline: the new violations."""
    return [f"{d}: {kind} {n} (baseline {base.get(d, {}).get(kind, 0)})"
            for d, row in sorted(now.items()) for kind, n in sorted(row.items()) if n > base.get(d, {}).get(kind, 0)]


if __name__ == "__main__":
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(count_tree(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(count_tree(), indent=1, sort_keys=True))
