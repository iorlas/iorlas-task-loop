"""ID-shape operations belong to the beads adapter; audit source and exercise the audit on representative regressions."""
import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
ID_NAMES = {"bead", "bead_id", "task_id", "bid", "parent_id"}
SHAPE_METHODS = {"split", "rsplit", "partition", "rpartition", "startswith", "endswith", "removeprefix", "removesuffix"}
ID_READERS = {"bead_ids", "prefix_of", "mentioned_ids", "_bead_token"}
ID_PATTERNS = ("(?:[.-][a-z0-9]+)", "-[A-Za-z0-9]+(?:\\.[0-9]+)")
# This normalizer is shared by domain outcome/storm policy; moving it requires changing that dependency boundary.
ENTANGLED = {"taskloop/domain/report/matchers.py": {"_bead_token", "CANDIDATE", "BEAD_PREFIXES"}}


def id_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in ID_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in ID_NAMES or (node.attr == "id" and isinstance(node.value, ast.Name) and node.value.id in {"b", "task"})
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str" and node.args:
        return id_value(node.args[0])
    return False


def problems(tree: ast.AST) -> list[int]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ID_READERS:
            found.append(node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(p in node.value for p in ID_PATTERNS):
            found.append(node.lineno)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method, value = node.func.attr, node.func.value
        searching = method in {"findall", "search", "match", "fullmatch"} and any(id_value(a) for a in node.args)
        if (method in SHAPE_METHODS and id_value(value)) or searching:
            found.append(node.lineno)
    return found


def node_name(node: ast.AST) -> str:
    if isinstance(node, ast.FunctionDef):
        return node.name
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ""


def outside_adapter(path: Path) -> bool:
    rel = path.relative_to(SRC)
    return not (rel.parts[:2] == ("taskloop", "adapters")
                and (path.stem.startswith("bd") or path.stem == "beadtools"))


class OpaqueTaskIds(unittest.TestCase):
    def test_source_has_no_new_id_shape_readers_outside_beads(self):
        found = []
        for path in sorted(SRC.rglob("*.py")):
            if "_vendor" in path.parts or not outside_adapter(path):
                continue
            rel = path.relative_to(SRC).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            tree.body = [node for node in tree.body if node_name(node) not in ENTANGLED.get(rel, set())]
            found.extend(f"{rel}:{line}" for line in problems(tree))
        self.assertEqual(found, [], "Task IDs are opaque: move shape readers into the beads adapter")

    def test_audit_rejects_id_parses(self):
        for source in ('bead.split("-")', 'e.bead.rsplit(".", 1)', 'task_id.startswith(prefix)',
                       'b.id.partition("-")', 'str(bead_id).split(".")', 're.search(pattern, bid)', 'pattern.match(bead_id)',
                       'pattern = r"(?:[.-][a-z0-9]+)+"',
                       'def bead_ids(prefix, text):\n    return []'):
            with self.subTest(source=source):
                self.assertTrue(problems(ast.parse(source)))

    def test_audit_allows_other_formats_and_opaque_lookups(self):
        source = 'version.split(".")\npath.rsplit("/", 1)\nstore.show(bead_id)\nb.parent\nprefix_of(e.bead)'
        self.assertEqual(problems(ast.parse(source)), [])
