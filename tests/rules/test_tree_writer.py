"""Only the check Fixer may write the worktree: under tlgate no module but fixer.py names `stage_all` or `tree_writer`
(testing.py supplies the fake host), and the
CheckoutView every other check reads through has no way to stage."""
import ast
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
from tlgate.host import CheckoutView, TreeWriter

CHECKS = Path(__file__).resolve().parents[2] / "packages" / "gate" / "src" / "tlgate"
WRITE_NAMES = {"stage_all", "tree_writer"}


def users(path: Path) -> set[str]:
    names = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Attribute) and n.attr in WRITE_NAMES:
            names.add(n.attr)
        elif isinstance(n, ast.Name) and n.id in WRITE_NAMES:
            names.add(n.id)
    return names


class OnlyTheFixerWrites(Case):
    def test_no_check_module_but_the_fixer_reaches_for_the_write_capability(self):
        found = {f.name: users(f) for f in sorted(CHECKS.glob("*.py")) if f.name not in ("fixer.py", "host.py", "testing.py") and users(f)}
        assert found == {}, "a check reads the tree through CheckoutView; only fixer.py stages (host.TreeWriter)"

    def test_the_fixer_does_use_it(self):
        assert users(CHECKS / "fixer.py") == WRITE_NAMES

    def test_the_read_view_cannot_stage(self):
        assert "stage_all" not in dir(CheckoutView)
        assert "stage_all" in dir(TreeWriter)
