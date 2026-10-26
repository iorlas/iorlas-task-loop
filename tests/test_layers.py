"""E0 (tl-7y6.6.16): the layer check. Feature folders under skills/task-loop may import only the folders in ALLOWED.

Source: 84-self-hosting sec 2.2: everything -> core; write -> checks; review -> checks; land -> checks, slots; loop -> all.
The flat modules (engine.py, tl.py ...) are the hub until moved: they may import anything, and a flat module shadows a folder of
the same name (loop.py vs loop/) until that folder takes over. Any edge not in ALLOWED is a reviewed change to this table.
"""
import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "task-loop"
FOLDERS = ("core", "lanes", "checks", "asks", "plan", "slots", "review", "loop", "release", "land", "look", "write", "dash")
ALL = frozenset(FOLDERS)
ALLOWED = {
    "core": frozenset(),
    "lanes": frozenset({"core"}),
    "checks": frozenset({"core"}),
    "asks": frozenset({"core"}),
    "plan": frozenset({"core"}),
    "slots": frozenset({"core"}),
    "look": frozenset({"core"}),
    "release": frozenset({"core"}),
    "dash": frozenset({"core"}),
    "write": frozenset({"core", "checks"}),
    "review": frozenset({"core", "checks"}),
    "land": frozenset({"core", "checks", "slots"}),
    "loop": ALL - {"loop"},
}


def imported_tops(tree):
    """Top-level names a module imports, by absolute import; `from ..x import y` (two dots up, out of a folder) counts as x."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 2 and node.module:
                yield node.module.split(".")[0]
            elif node.level >= 2:
                for a in node.names:
                    yield a.name
            elif node.level == 0 and node.module:
                yield node.module.split(".")[0]


def violations(skill=SKILL):
    """['<file>: <from>/ imports <to>/ (<from> -> <to> is not allowed)'] for every folder-to-folder import outside ALLOWED."""
    skill = Path(skill)
    flat = {p.stem for p in skill.glob("*.py")}
    found = []
    for src in FOLDERS:
        for py in sorted((skill / src).rglob("*.py")):
            for top in sorted(set(imported_tops(ast.parse(py.read_text(encoding="utf-8"), str(py))))):
                if top in ALL and top not in flat and top != src and top not in ALLOWED[src]:
                    found.append("%s: %s/ imports %s/ (%s -> %s is not allowed)" % (py.relative_to(skill), src, top, src, top))
    return found


class Table(unittest.TestCase):
    def test_every_edge_names_known_folders_and_core_imports_nothing(self):
        self.assertEqual(set(ALLOWED), ALL)
        for src, to in ALLOWED.items():
            self.assertLessEqual(to, ALL, src)
            self.assertNotIn(src, to)
        self.assertEqual(ALLOWED["core"], frozenset())

    def test_every_folder_other_than_core_may_import_core(self):
        for src in FOLDERS:
            if src != "core":
                self.assertIn("core", ALLOWED[src], src)

    def test_no_import_cycle_in_the_table(self):
        state = {}

        def visit(n):
            self.assertNotEqual(state.get(n), 1, "cycle through %s" % n)
            if n not in state:
                state[n] = 1
                for m in ALLOWED[n]:
                    visit(m)
                state[n] = 2
        for n in FOLDERS:
            visit(n)

    def test_every_folder_exists(self):
        for f in FOLDERS:
            self.assertTrue((SKILL / f).is_dir(), f)


class Tree(unittest.TestCase):
    def test_the_real_tree_has_no_sideways_import(self):
        self.assertEqual(violations(), [])

    def make(self, files, flat=()):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for rel, text in files.items():
            p = Path(d.name) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for name in flat:
            (Path(d.name) / (name + ".py")).write_text("", encoding="utf-8")
        return d.name

    def test_a_planted_sideways_import_fails_naming_both_folders(self):
        root = self.make({"checks/x.py": "import slots\n", "slots/__init__.py": ""})
        out = violations(root)
        self.assertEqual(len(out), 1)
        self.assertIn("checks -> slots", out[0])

    def test_from_import_and_relative_import_out_of_a_folder_are_caught(self):
        root = self.make({"review/a.py": "from land.finish import go\n", "write/b.py": "from ..asks import x\n"})
        out = violations(root)
        self.assertEqual(len(out), 2)
        self.assertTrue(any("review -> land" in o for o in out))
        self.assertTrue(any("write -> asks" in o for o in out))

    def test_allowed_edges_and_sibling_modules_pass(self):
        root = self.make({"land/a.py": "import checks\nfrom slots import s\nimport core\n", "write/b.py": "import checks\nimport helper\n",
                          "loop/c.py": "import land, review, dash\n", "core/d.py": "import os\n"})
        self.assertEqual(violations(root), [])

    def test_core_importing_a_feature_fails(self):
        out = violations(self.make({"core/a.py": "import checks\n"}))
        self.assertEqual(len(out), 1)
        self.assertIn("core -> checks", out[0])

    def test_a_flat_module_of_the_same_name_is_the_hub_not_the_folder(self):
        self.assertEqual(violations(self.make({"dash/a.py": "import loop\n"}, flat=["loop"])), [])
        self.assertEqual(len(violations(self.make({"dash/a.py": "import loop\n"}))), 1)


if __name__ == "__main__":
    unittest.main()
