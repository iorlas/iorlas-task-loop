"""The land never merges on trust: Stack.merged asks the tree guard before the forge merges and checks the landed commit after it
(docs/design/merge-queue.md section 2, layers 1 and 3)."""
import ast
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

STACK = Path(__file__).resolve().parents[2] / "src" / "taskloop" / "app" / "land" / "stack.py"


def merged_calls() -> list[str]:
    """The attribute calls of Stack.merged in source order, as `a.b` text."""
    tree = ast.parse(STACK.read_text(encoding="utf-8"))
    fn = next(n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "Stack" for n in c.body
              if isinstance(n, ast.FunctionDef) and n.name == "merged")
    calls = sorted((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)),
                   key=lambda n: (n.lineno, n.col_offset))
    return [ast.unparse(n.func) for n in calls]


class MergedAssertsTheTree(Case):
    def test_merged_asks_the_guard_before_the_merge_and_verifies_after_it(self):
        calls = merged_calls()
        assert "self.trees.refuse" in calls and "self.trees.verify" in calls
        assert calls.index("self.trees.refuse") < calls.index("self.forge.merge") < calls.index("self.trees.verify")
