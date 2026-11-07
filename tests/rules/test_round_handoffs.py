"""ROUNDRESULT: a write, check or review round hands what it decided to StageLoop by value (a RoundResult); it assigns none of these fields
on the engine. An AST scan of the three round files fails an assignment or augmented assignment to one of them on the host."""
import ast
from pathlib import Path

from rules.gate_rules import parsed

APP_WRITE = Path(__file__).resolve().parents[2] / "packages/work/src/tlwork/write"
ROUNDS = ("write_round.py", "check_round.py", "review_round.py")
HANDED = {"last_run", "stuck_why", "last_summary", "writer_family", "write_rounds", "stats"}  # engine fields a round's result carries
HOST = {"e", "host"}


def handed_writes(tree: ast.Module) -> list[tuple[int, str]]:
    """[(line, field)]: `e.<field> = ...`, `e.<field> += ...`, `e.<field>[k] = ...`, `e.<field>.append/extend(...)` on the host."""
    found = []
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
        for t in targets:
            base = t.value if isinstance(t, ast.Subscript) else t
            if isinstance(base, ast.Attribute) and base.attr in HANDED and isinstance(base.value, ast.Name) and base.value.id in HOST:
                found.append((base.lineno, base.attr))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"append", "extend"}:
            owner = n.func.value
            if isinstance(owner, ast.Attribute) and owner.attr in HANDED and isinstance(owner.value, ast.Name) and owner.value.id in HOST:
                found.append((owner.lineno, owner.attr))
    return found


def test_the_rounds_assign_no_hand_off_on_the_engine():
    bad = [f"{name}:{line} e.{field}" for name in ROUNDS for line, field in handed_writes(parsed(APP_WRITE / name)[1])]
    why = "a round returns these in its RoundResult (app/write/state.py); StageLoop.apply puts them on the engine:\n"
    assert not bad, why + "\n".join(bad)


def test_the_scan_sees_each_form():
    tree = ast.parse("e.stuck_why = 'x'\ne.stats['rounds'] += 1\ne.write_rounds.append(1)\ne.other = 1\nself.e.stuck_why = 2\n")
    assert [f for _, f in handed_writes(tree)] == ["stuck_why", "stats", "write_rounds"]


def leftover_writes(tree: ast.Module) -> list[int]:
    """Find list mutations and field assignments, regardless of the host's name."""
    def is_leftovers(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "leftovers"

    found = []
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and any(is_leftovers(target) for target in targets):
            found.append(node.lineno)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"append", "extend", "insert"} and is_leftovers(node.func.value)):
            found.append(node.lineno)
    return found


def test_stages_write_leftovers_only_through_the_sink():
    app = APP_WRITE.parent
    bad = [f"{path.relative_to(app)}:{line}" for stage in ("plan", "review", "write", "look")
           for path in sorted((app / stage).rglob("*.py")) for line in leftover_writes(parsed(path)[1])]
    assert not bad, "stages must call leftover_sink:\n" + "\n".join(bad)


def test_the_leftover_scan_sees_each_form():
    tree = ast.parse("x.leftovers.append(lo)\ny.leftovers.extend(items)\nz.leftovers.insert(0, lo)\n"
                     "host.leftovers += items\nself.hand.leftovers = []\ne.other = []\n"
                     "e.leftover_sink.extend(items)\n")
    assert sorted(leftover_writes(tree)) == [1, 2, 3, 4, 5]
