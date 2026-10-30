"""STATEFILES (tl-3u6.9): a state file of ours is a Rec on a Doc, written by the one atomic writer (contracts/stores.JsonStore ->
atomic_io). Under taskloop/app no module replaces a file by hand (`os.replace`) or writes JSON text with `write_text`.
ALLOWED lists, per file, the sites that must stay (why in the comment). A count may only shrink: lower it when a site moves."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "taskloop" / "app"

ALLOWED: dict[str, int] = {
    "src/taskloop/app/run/engine.py": 1,  # runs/<run>/plan.json: the plan's wire copy for the dashboard (PLANREF owns the plan's typing)
    "src/taskloop/app/run/worker_call.py": 1,  # runs/<run>/<node>-<n>.json: the lane's raw answer, a shape the lane contract owns
}


def hand_writes(tree: ast.AST) -> list[int]:
    """Lines of `os.replace(...)` and of `.write_text(...)` calls that carry JSON (the call's own text names json)."""
    found = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        is_replace = n.func.attr == "replace" and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"
        if is_replace or (n.func.attr == "write_text" and "json" in ast.unparse(n)):
            found.append(n.lineno)
    return found


def scan() -> dict[str, int]:
    out = {}
    for f in sorted(APP.rglob("*.py")):
        lines = hand_writes(ast.parse(f.read_text(encoding="utf-8")))
        if lines:
            out[str(f.relative_to(ROOT))] = len(lines)
    return out


class StateFilesHaveOneWriter(unittest.TestCase):
    def test_no_new_hand_written_state_file_under_app(self):
        got = scan()
        grown = {k: v for k, v in got.items() if v > ALLOWED.get(k, 0)}
        self.assertEqual(grown, {}, "a state file is a Rec on a JsonStore (contracts/stores.py), not os.replace / write_text")

    def test_the_allowlist_only_shrinks(self):
        got = scan()
        stale = {k: v for k, v in ALLOWED.items() if got.get(k, 0) < v}
        self.assertEqual(stale, {}, "a listed site moved: lower or delete its entry")

    def test_the_scan_sees_planted_writes(self):
        src = "import os\nos.replace(a, b)\np.write_text(json.dumps(x))\np.write_text('md')\n"
        self.assertEqual(hand_writes(ast.parse(src)), [2, 3])


if __name__ == "__main__":
    unittest.main()
