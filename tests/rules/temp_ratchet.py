"""The temp-path ratchet's counter: where code names a temp location itself instead of asking src/taskloop/contracts/scratch.py.

A site is a `tempfile` attribute or import, or a string constant holding /tmp, /var/tmp or TMPDIR, anywhere in src/, dev/,
skills/ and tests/
but scratch.py itself. `temp_baseline.json` holds today's count per directory; `PYTHONPATH=tests uv run python -m
rules.temp_ratchet --write`
rewrites it after a cleanup lowers one."""
import ast
import json
import sys
from pathlib import Path

from rules.gate_rules import ROOT, SKIP_DIRS, parsed

BASELINE = Path(__file__).with_name("temp_baseline.json")
HOME_FILE = "src/taskloop/contracts/scratch.py"
SCAN = ("src", "dev", "skills", "tests")
NEEDLES = ("/tmp", "/var/tmp", "TMPDIR")


def named(node: ast.AST) -> bool:
    """One site: `tempfile.x`, `from tempfile import`, or a short string holding a system temp name."""
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == "tempfile"
    if isinstance(node, ast.ImportFrom):
        return node.module == "tempfile"
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and any(n in node.value for n in NEEDLES)


def sites(tree: ast.Module) -> int:
    return sum(named(node) for node in ast.walk(tree))


def count_tree(root: Path = ROOT) -> dict[str, int]:
    out: dict[str, int] = {}
    for top in SCAN:
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root)
            if SKIP_DIRS & set(rel.parts) - {"fixtures"} or "_vendor" in rel.parts or rel.as_posix() == HOME_FILE:
                continue
            if "rules" in rel.parts and rel.name in ("temp_ratchet.py", "test_temp_ratchet.py"):
                continue
            n = sites(parsed(path)[1])
            if n:
                key = "/".join(rel.parts[:-1])
                out[key] = out.get(key, 0) + n
    return out


def grown(now: dict[str, int], base: dict[str, int]) -> list[str]:
    return [f"{d}: {n} (baseline {base.get(d, 0)})" for d, n in sorted(now.items()) if n > base.get(d, 0)]


if __name__ == "__main__":
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(count_tree(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(count_tree(), indent=1, sort_keys=True))
