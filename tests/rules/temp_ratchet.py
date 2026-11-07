"""The temp-path ratchet's counter: where code names a temp location itself instead of asking packages/kernel/src/tlkernel/scratch.py.

A site is a `tempfile` attribute or import, or a string constant holding /tmp, /var/tmp or TMPDIR, anywhere in src/, dev/, skills/ and
tests/ but scratch.py itself. Judged on the change (ratchet_change.py): a rise over the files the change touches fails unless a commit
says `Ratchet-allow: temp +N reason`."""
import ast
from pathlib import Path

from rules.gate_rules import SKIP_DIRS

HOME_FILE = "packages/kernel/src/tlkernel/scratch.py"
SCAN = ("src", "dev", "skills", "tests")
RATCHET_FILES = ("temp_ratchet.py", "test_temp_ratchet.py", "test_ratchets.py", "test_ratchets_change.py")  # they quote sites
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


def file_counts(rel: str, tree: ast.Module) -> dict[str, int]:
    """{"site": n} of one file under src/, dev/, skills/ or tests/ that may name a temp location; empty for any other file."""
    path = Path(rel)
    if path.parts[0] not in SCAN or SKIP_DIRS & set(path.parts) - {"fixtures"} or "_vendor" in path.parts or rel == HOME_FILE:
        return {}
    if "rules" in path.parts and path.name in RATCHET_FILES:
        return {}
    n = sites(tree)
    return {"site": n} if n else {}
