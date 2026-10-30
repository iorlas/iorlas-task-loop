"""Only the check Fixer may write the worktree: under app/checks no module but fixer.py names `stage_all` or `tree_writer`, and the
CheckoutView every other check reads through has no way to stage."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from taskloop.app.checks.host import CheckoutView, TreeWriter

CHECKS = Path(__file__).resolve().parents[2] / "src" / "taskloop" / "app" / "checks"
WRITE_NAMES = {"stage_all", "tree_writer"}


def users(path: Path) -> set[str]:
    names = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Attribute) and n.attr in WRITE_NAMES:
            names.add(n.attr)
        elif isinstance(n, ast.Name) and n.id in WRITE_NAMES:
            names.add(n.id)
    return names


class OnlyTheFixerWrites(unittest.TestCase):
    def test_no_check_module_but_the_fixer_reaches_for_the_write_capability(self):
        found = {f.name: users(f) for f in sorted(CHECKS.glob("*.py")) if f.name not in ("fixer.py", "host.py") and users(f)}
        self.assertEqual(found, {}, "a check reads the tree through CheckoutView; only fixer.py stages (host.TreeWriter)")

    def test_the_fixer_does_use_it(self):
        self.assertEqual(users(CHECKS / "fixer.py"), WRITE_NAMES)

    def test_the_read_view_cannot_stage(self):
        self.assertNotIn("stage_all", dir(CheckoutView))
        self.assertIn("stage_all", dir(TreeWriter))
