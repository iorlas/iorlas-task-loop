"""A1 (tl-rules): the rules the linters cannot express, as one stdlib test (88-target-architecture sections 3 and 6).

What it enforces, over every .py under src/, skills/, dev/ and tests/ (EXEMPT_DIRS is skipped by the caps):
  caps      400 SLOC per file, 80 per function, 800 per test file; SLOC = non-blank, non-comment, non-docstring lines by tokenize.
            Every cap violation that exists today is listed by file name in tests/rules/rules_ratchet.json
            ("oversize" / "oversize_functions"). A listed entry may be removed or lowered, never added.
            Run `python3 tests/rules/gate_rules.py --measure` to see the current table.
  layers    not here: the `.importlinter` contracts (layers, app slices, dashboard, `import re` placement) run in `just rules`;
            lazy imports are ruff PLC0415, banned modules TID251, module docstrings D100 (ruff.toml).
  placement our file names only in contracts/paths.py; no mutable module global in domain/app/cli/hook/dash.
  vendor    the vendored shelf copy is unedited and matches dev/vendor.json (VendorGuard, Smoke); EXEMPT_DIRS skips it for the caps.
  pyrefly   no baseline file: pyrefly check is clean, and a deliberate exception is a `# pyrefly: ignore[kind]` with its reason.
The older folder table for skills/task-loop (ALLOWED, formerly tests/test_layers.py) stays here.
"""
import ast
import functools
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import tomllib
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskloop  # noqa: E402, F401  (puts the vendored shelf packages on sys.path)

# isort: split
import vendor  # noqa: E402
from git_porcelain import GitUnavailable, Identity, RealRepo  # noqa: E402
from git_porcelain.testing import FakeRepo, git, hermetic_env  # noqa: E402
from support.procsim import real_proc  # noqa: E402

RATCHET = Path(__file__).with_name("rules_ratchet.json")
SCAN = ("src", "skills", "dev", "tests")
SKIP_DIRS = frozenset({".git", ".worktrees", ".slots", ".task", "__pycache__", "fixtures", "node_modules", ".venv"})
# The one place the size/file-count rules skip a path (the vendored shelf copy, dev/vendor.py). Nothing else is exempt.
EXEMPT_DIRS = ("skills/task-loop/_vendor",)
FILE_CAP, TEST_FILE_CAP, FUNC_CAP = 400, 800, 80

# -- per-repo constants (the only lines that differ between iorlas-task-loop and iorlas-delegate) ------------------------------------
DASH_PKGS = frozenset({"taskloop_dash"})
FOREIGN_NAMES = ()                          # this plugin never names these in src/ text
PATH_LITERALS = ("engine/", "plan.json", "engine.lock", ".task/", "asks/", "checkpoints/")

# -- mutable globals ---------------------------------------------------------------------------------------------------------------
MUTABLE_LAYERS = frozenset({"domain", "app", "cli", "hook", "dash"})
MUTABLE_CALLS = frozenset({"list", "dict", "set", "defaultdict", "deque", "OrderedDict", "Counter", "bytearray"})


# -- measuring -----------------------------------------------------------------------------------------------------------------------
def py_files(root, scan=SCAN):
    for top in scan:
        base = Path(root) / top
        if base.is_dir():
            for path in sorted(base.rglob("*.py")):
                rel = path.relative_to(root)
                if not SKIP_DIRS & set(rel.parts) and not rel.as_posix().startswith(tuple(d + "/" for d in EXEMPT_DIRS)):
                    yield path


def docstring_nodes(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.append(first)
    return found


def sloc_lines(text, tree):
    """The set of line numbers that hold code: not blank, not a comment, not part of a docstring."""
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
    lines = set()
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type not in skip:
            lines.update(range(tok.start[0], tok.end[0] + 1))
    for node in docstring_nodes(tree):
        lines -= set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def walk_defs(node, prefix=""):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield prefix + child.name, child
            yield from walk_defs(child, prefix + child.name + ".")
        elif isinstance(child, ast.ClassDef):
            yield from walk_defs(child, prefix + child.name + ".")
        else:
            yield from walk_defs(child, prefix)


@functools.cache
def _parsed(path: str, _stamp: tuple[int, int]) -> tuple[str, ast.Module]:
    text = Path(path).read_text(encoding="utf-8")
    return text, ast.parse(text, path)


def parsed(path) -> tuple[str, ast.Module]:
    """(text, tree) of a .py file, parsed once per process for every check that reads it (keyed on its mtime and size)."""
    st = os.stat(path)
    return _parsed(str(path), (st.st_mtime_ns, st.st_size))


def measure(path):
    """(file SLOC, {qualified function name: SLOC}) for one .py file."""
    text, tree = parsed(path)
    lines = sloc_lines(text, tree)
    funcs = {}
    for qual, node in walk_defs(tree):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        size = len(lines & set(range(start, (node.end_lineno or node.lineno) + 1)))
        funcs[qual] = max(size, funcs.get(qual, 0))
    return len(lines), funcs


def file_cap(rel):
    return TEST_FILE_CAP if rel.startswith("tests/") else FILE_CAP


def measure_tree(root):
    """{'files': {rel: sloc over its cap}, 'functions': {'rel::qual': sloc over FUNC_CAP}}: every violation in the tree."""
    files, funcs = {}, {}
    for path in py_files(root):
        rel = path.relative_to(root).as_posix()
        size, per_func = measure(path)
        if size > file_cap(rel):
            files[rel] = size
        funcs.update({f"{rel}::{q}": n for q, n in per_func.items() if n > FUNC_CAP})
    return {"files": files, "functions": funcs}


def load_ratchet():
    return json.loads(RATCHET.read_text(encoding="utf-8"))


def ratchet_problems(actual, known, label, ceiling=lambda key: True):
    """A violation absent from `known` fails; `known` entries that are fixed (or gone) must be removed; a ceiling may not be exceeded.
    `ceiling(key)` False means membership only (test files: the loops keep adding tests to the big ones)."""
    out = []
    for key, size in sorted(actual.items()):
        if key not in known:
            out.append(f'{label} over cap: {key} = {int(size)}. Split it; do not add it to the table.')
        elif ceiling(key) and size > known[key]:
            out.append(f"{label} grew: {key} = {int(size)} > recorded {int(known[key])}")
    for key in sorted(set(known) - set(actual)):
        out.append(f'{label} now within its cap (or gone): delete "{key}" from tests/rules/rules_ratchet.json')
    return out


def cap_problems(root=ROOT, known=None):
    known = load_ratchet() if known is None else known
    actual = measure_tree(root)
    def not_test(key):
        return not key.startswith("tests/")
    return (ratchet_problems(actual["files"], known["oversize"], "file", not_test)
            + ratchet_problems(actual["functions"], known["oversize_functions"], "function", not_test))


# -- import graph over src/ ------------------------------------------------------------------------------------------------------------
def src_files(root):
    base = Path(root) / "src"
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.py")):
        parts = path.relative_to(base).parts
        if "_vendor" not in parts and "__pycache__" not in parts:
            yield path, parts


def layer_of(parts):
    pkg = parts[0]
    if pkg in DASH_PKGS:
        return "dash"
    return parts[1] if len(parts) > 2 else None


def cycle_in(edges):
    graph = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            return [*path[path.index(n):], n]
        if state.get(n) == 2:
            return None
        state[n] = 1
        for m in sorted(graph.get(n, ())):
            found = visit(m, [*path, n])
            if found:
                return found
        state[n] = 2
        return None
    for n in sorted(graph):
        found = visit(n, [])
        if found:
            return found
    return None


# -- placement rules over src/ ---------------------------------------------------------------------------------------------------------
def is_final(annotation):
    return any(
        (isinstance(n, ast.Name) and n.id == "Final") or (isinstance(n, ast.Attribute) and n.attr == "Final") for n in ast.walk(annotation)
    )


def mutable_value(value):
    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    return isinstance(value, ast.Call) and getattr(value.func, "id", getattr(value.func, "attr", "")) in MUTABLE_CALLS


def module_statements(tree):
    for node in tree.body:
        if isinstance(node, (ast.If, ast.Try)):
            yield from node.body
        else:
            yield node


def mutable_globals(tree):
    declared = {n for node in ast.walk(tree) if isinstance(node, ast.Global) for n in node.names}
    found = []
    for node in module_statements(tree):
        if isinstance(node, ast.Assign):
            names, value, annotation = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value, None
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            names, value, annotation = [node.target.id], node.value, node.annotation
        else:
            continue
        for name in names:
            if name.startswith("__") and name.endswith("__"):
                continue
            if annotation is not None and is_final(annotation):
                continue
            if mutable_value(value) or (isinstance(value, ast.Constant) and value.value is None and name in declared):
                found.append((name, node.lineno))
    return found


def file_literals(tree):
    skip = {id(n.value) for n in docstring_nodes(tree)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.value, node.lineno


def placement_problems(root):
    out = []
    for path, parts in src_files(root):
        rel, layer = "src/" + "/".join(parts), layer_of(parts)
        text, tree = parsed(path)
        if layer in MUTABLE_LAYERS:
            out += [f"{rel}:{n}: mutable module global {name}" for name, n in mutable_globals(tree)]
        if parts[1:] != ("contracts", "paths.py"):
            out += [f"{rel}:{n}: file name {lit!r} belongs in contracts/paths.py" for lit, n in file_literals(tree)
                    if any(p in lit for p in PATH_LITERALS)]
        out += [f"{rel}: names {n!r} (the two plugins never name each other)" for n in FOREIGN_NAMES if n in text]
    return out


def src_problems(root=ROOT):
    return placement_problems(root)


# -- no signal is sent outside stream-proc ------------------------------------------------------------------------------------------
# Stopping a process (a worker, a check, the dashboard, a stopped run-task) is `stream_proc.stop_tree` (through adapters/procs.py:
# `stop_tree`, `stop_pid`, `capture`); a liveness read is `stream_proc.alive`. Installing a handler (signal.signal) is not a send.
SENDS = (
    r"\bos\.kill(pg)?\(",
    r"\bsignal\.(raise_signal|pthread_kill|alarm|setitimer)\(",
    r"\.send_signal\(",
    r"\.terminate\(\)",
    r"\.kill\(\)",
    r"\bkillpg\(",
)
SIGNAL_EXCEPTIONS: dict[str, str] = {}  # "path" -> why it still sends a signal itself; may only shrink


def signal_sends(root=ROOT):
    found = {}
    for base in ("src", "skills", "dev"):
        for path in sorted((Path(root) / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(tuple(d + "/" for d in EXEMPT_DIRS)) or SKIP_DIRS & set(path.relative_to(root).parts):
                continue
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
            if any(re.search(pat, ln) for ln in lines for pat in SENDS):
                found[rel] = True
    return found


class Signals(unittest.TestCase):
    def test_no_signal_is_sent_outside_stream_proc(self):
        for rel in signal_sends():
            self.assertIn(rel, SIGNAL_EXCEPTIONS, f"{rel} sends a signal: go through stream_proc (stop_tree / run / alive)")

    def test_the_exception_table_only_shrinks(self):
        found = signal_sends()
        for rel in SIGNAL_EXCEPTIONS:
            self.assertIn(rel, found, f"{rel} no longer sends a signal: delete its line")

    def test_every_child_of_the_engine_is_spawned_through_stream_proc(self):
        """The engine's SIGTERM handler raises, even inside Popen(): a child spawned bare is left owned by nobody."""
        bare = [p.relative_to(ROOT).as_posix() for base in ("src", "skills") for p in sorted((ROOT / base).rglob("*.py"))
                if not p.relative_to(ROOT).as_posix().startswith(tuple(d + "/" for d in EXEMPT_DIRS))
                and re.search(r"\bsubprocess\.Popen\(", p.read_text(encoding="utf-8"))]
        self.assertEqual(bare, [], "spawn through taskloop.adapters.procs (popen_held / spawn / capture)")

    def test_the_dash_starts_no_process_and_reaches_bd_only_through_the_store_port(self):
        """tl-2ve: the dashboard only reads; bd comes in as `Ports.store` (the engine's BdStore, the one process site)."""
        bad = [
            p.relative_to(ROOT).as_posix()
            for p in sorted((ROOT / "src" / "taskloop_dash").rglob("*.py"))
            if re.search(r"\bsubprocess\b|\bPopen\b|\bos\.(system|exec\w*|spawn\w*)\(|\brun\(|\bports\.bd\b", p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(bad, [])

    def test_the_rule_finds_a_send(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "bad.py").write_text("import os\nos.killpg(1, 9)\n")
            (Path(d) / "src" / "ok.py").write_text("import signal\nsignal.signal(signal.SIGTERM, print)\n# os.kill(1, 9)\n")
            self.assertEqual(list(signal_sends(d)), ["src/bad.py"])


# -- no shell on a check ---------------------------------------------------------------------------------------------------------------
SHELL_NAMES = frozenset({"sh", "bash", "zsh", "dash"})
SHELL_FLAGS = frozenset({"-c", "-lc", "-ic", "-cl", "-ec", "-ce"})
SPLITTER = re.compile(r"split_top|shell_?split|split_shell|shell_?words", re.I)
SHELL_TEXT = re.compile(r"\b(?:ba|z|da)?sh\s+-[a-z]*c\b|\bbash\s+-n\b")


def shell_problems(root=ROOT):
    """Where a check could reach a shell again: shell=True, a shell named with -c in an argv or a text, `bash -n`, a shell splitter."""
    found = []
    for base in ("src", "skills"):
        for path in sorted((Path(root) / base).rglob("*.py")):
            rel = path.relative_to(root)
            if SKIP_DIRS & set(rel.parts) or rel.as_posix().startswith(tuple(d + "/" for d in EXEMPT_DIRS)):
                continue
            tree = parsed(path)[1]
            docs = {id(d.value) for d in docstring_nodes(tree)}
            for node in ast.walk(tree):
                why = ""
                if (
                    isinstance(node, ast.keyword)
                    and node.arg == "shell"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is True
                ):
                    why = "shell=True"
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and SPLITTER.search(node.name):
                    why = "a shell splitter: " + node.name
                elif isinstance(node, (ast.Name, ast.Attribute)) and SPLITTER.search(getattr(node, "id", "") or getattr(node, "attr", "")):
                    why = "a shell splitter"
                elif (
                    isinstance(node, (ast.List, ast.Tuple))
                    and len(node.elts) >= 2
                    and all(isinstance(e, ast.Constant) for e in node.elts[:2])
                ):
                    first, second = (cast(ast.Constant, e).value for e in node.elts[:2])
                    if isinstance(first, str) and Path(first).name in SHELL_NAMES and second in SHELL_FLAGS | {"-n"}:
                        why = "a shell run with " + str(second)
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs
                    and SHELL_TEXT.search(node.value)
                ):
                    why = "shell text: " + node.value[:40]
                if why:
                    found.append("{}:{:d} {}".format(rel.as_posix(), int(getattr(node, "lineno", 0)), why))
    return found


class NoShell(unittest.TestCase):
    def test_no_check_text_goes_through_a_shell_and_no_shell_splitter_is_left(self):
        self.assertEqual(shell_problems(), [], "a check is an argv list: no shell=True, bash -c / -n, or split_top-style splitter")

    def test_the_rule_finds_each_way_back_to_a_shell(self):
        bad = ("import subprocess\nsubprocess.run('x', shell=True)\nsubprocess.run(['bash', '-c', 'x'])\nrun('bash -n f')\n"
               "def split_top(t): pass\nshell_split(t)\n")
        ok = "import shlex, subprocess\nsubprocess.run(['git', 'status'])\nshlex.split('a b')\nFLAGS = ('-c', '-lc')\nx = ['sh']\n"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "bad.py").write_text(bad)
            (Path(d) / "src" / "ok.py").write_text(ok)
            got = shell_problems(d)
        self.assertEqual(sorted({g.split(":")[0] for g in got}), ["src/bad.py"])
        self.assertEqual(len(got), 5, got)


# -- no process probe ------------------------------------------------------------------------------------------------------------------
PROBES = frozenset({"lsof", "ps", "pgrep", "tasklist"})
SPAWNERS = frozenset({"run", "Popen", "call", "check_call", "check_output", "capture", "spawn", "which"})


def call_name(node):
    return getattr(node.func, "attr", "") or getattr(node.func, "id", "")


def probe_problems(root=ROOT):
    """Where an argv names lsof, ps, pgrep or tasklist (a list or tuple starting with one, or a spawn call given one): what a process
    does is read from a typed fact (the live file, the answer's worker.end, a lock's holder record), never guessed from a probe."""
    found = []
    for base in ("src", "skills"):
        for path in sorted((Path(root) / base).rglob("*.py")):
            rel = path.relative_to(root)
            if SKIP_DIRS & set(rel.parts) or rel.as_posix().startswith(tuple(d + "/" for d in EXEMPT_DIRS)) or "_vendor" in rel.parts:
                continue
            for node in ast.walk(parsed(path)[1]):
                head = None
                if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
                    head = node.elts[0]
                elif isinstance(node, ast.Call) and node.args and call_name(node) in SPAWNERS:
                    head = node.args[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str) and Path(head.value).name in PROBES:
                    found.append(f"{rel.as_posix()}:{int(head.lineno)} {head.value}")
    return found


class NoProbe(unittest.TestCase):
    def test_no_argv_names_lsof_ps_pgrep_or_tasklist(self):
        self.assertEqual(probe_problems(), [], "no process probe: read the typed fact (live file, worker.end, a lock's holder record)")

    def test_the_rule_finds_each_probe_and_passes_the_rest(self):
        bad = ("import subprocess\nsubprocess.run(['lsof', '-t', 'f'])\nx = ('/bin/ps', '-p', '1')\nsubprocess.Popen('pgrep')\n"
               "run(['tasklist'])\n")
        ok = "import subprocess\nsubprocess.run(['git', 'status'])\nNAMES = ['pstree-not', 'x']\nprint('ps')\n"
        vend = "x = ['ps', '-p', '1']\n"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src" / "_vendor").mkdir(parents=True)
            (Path(d) / "src" / "bad.py").write_text(bad)
            (Path(d) / "src" / "ok.py").write_text(ok)
            (Path(d) / "src" / "_vendor" / "v.py").write_text(vend)
            got = probe_problems(d)
        self.assertEqual({g.split(":")[0] for g in got}, {"src/bad.py"})
        self.assertEqual(len(got), 4, got)


# -- the older folder table --------------------------------------------------------------------------
SKILL = ROOT / "skills" / "task-loop"
FOLDERS = ("core", "asks", "plan", "slots", "review", "loop", "release", "land", "look", "write", "dash")
ALL = frozenset(FOLDERS)
ALLOWED = {
    "core": frozenset(),
    "asks": frozenset({"core"}),
    "plan": frozenset({"core"}),
    "slots": frozenset({"core"}),
    "look": frozenset({"core"}),
    "release": frozenset({"core"}),
    "dash": frozenset({"core"}),
    "write": frozenset({"core"}),
    "review": frozenset({"core"}),
    "land": frozenset({"core", "slots"}),
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
            for top in sorted(set(imported_tops(parsed(py)[1]))):
                if top in ALL and top not in flat and top != src and top not in ALLOWED[src]:
                    found.append(f"{py.relative_to(skill)}: {src}/ imports {top}/ ({src} -> {top} is not allowed)")
    return found


# -- tests: the real tree --------------------------------------------------------------------------------------------------------------
class RealTree(unittest.TestCase):
    def test_caps_hold_except_the_known_oversize_table(self):
        self.assertEqual(cap_problems(), [])

    def test_the_ratchet_file_names_only_existing_keys_in_sorted_form(self):
        known = load_ratchet()
        for table in ("oversize", "oversize_functions"):
            self.assertEqual(list(known[table]), sorted(known[table]), table)
            for key, size in known[table].items():
                self.assertTrue((ROOT / key.split("::")[0]).is_file(), key)
                self.assertGreater(size, FUNC_CAP if "::" in key else FILE_CAP, key)

    def test_src_has_no_mutable_globals_and_names_its_files_only_in_paths(self):
        self.assertEqual(src_problems(), [])

    def test_the_old_folder_table_has_no_sideways_import(self):
        self.assertEqual(violations(), [])

    def test_pyrefly_has_no_baseline_every_error_is_fixed_or_ignored_with_a_reason(self):
        self.assertNotIn("baseline", tomllib.loads((ROOT / "pyrefly.toml").read_text(encoding="utf-8")))
        self.assertFalse((ROOT / "pyrefly-baseline.json").exists())

    def test_ruff_has_no_per_file_ignores_every_finding_is_fixed(self):
        lint = tomllib.loads((ROOT / "ruff.toml").read_text(encoding="utf-8"))["lint"]
        self.assertNotIn("per-file-ignores", lint)
        self.assertEqual(sorted(lint["ignore"]), ["PLR0913", "PLR0917", "PLR2004"])


# -- tests: planted trees --------------------------------------------------------------------------------------------------------------
class Planted(unittest.TestCase):
    def tree(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for rel, text in files.items():
            p = Path(d.name) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return Path(d.name)

    def problems(self, files):
        return src_problems(self.tree(files))

    def only(self, files, needle):
        found = self.problems(files)
        self.assertEqual(len(found), 1, found)
        self.assertIn(needle, found[0])

    def test_sloc_skips_blank_comment_and_docstring_lines(self):
        text = '"""doc\nmore"""\n\n# c\nx = 1\n\ndef f():\n    """d"""\n    return (1,\n            2)\n'
        self.assertEqual(sorted(sloc_lines(text, ast.parse(text))), [5, 7, 9, 10])

    def test_function_sloc_counts_nested_lines_and_decorators(self):
        root = self.tree({"skills/a.py": "import x\n\n@x.d\ndef f():\n    def g():\n        return 1\n    return g()\n"})
        size, funcs = measure(root / "skills" / "a.py")
        self.assertEqual((size, funcs["f"], funcs["f.g"]), (6, 5, 2))

    def test_a_file_over_its_cap_fails_unless_listed_and_a_fixed_one_must_leave_the_table(self):
        body = "x = 1\n" * (FILE_CAP + 1)
        root = self.tree({"skills/big.py": body, "tests/test_big.py": body})
        empty = {"oversize": {}, "oversize_functions": {}}
        self.assertEqual(len(cap_problems(root, empty)), 1)
        listed = {"oversize": {"skills/big.py": FILE_CAP + 1}, "oversize_functions": {}}
        self.assertEqual(cap_problems(root, listed), [])
        grown = {"oversize": {"skills/big.py": FILE_CAP}, "oversize_functions": {}}
        self.assertIn("grew", cap_problems(root, grown)[0])
        stale = {"oversize": {"skills/big.py": 500, "skills/gone.py": 500}, "oversize_functions": {}}
        self.assertIn("skills/gone.py", cap_problems(root, stale)[0])

    def test_a_test_file_may_be_over_400_up_to_800(self):
        root = self.tree({"tests/test_mid.py": "x = 1\n" * 700})
        self.assertEqual(cap_problems(root, {"oversize": {}, "oversize_functions": {}}), [])

    def test_a_function_over_80_fails_unless_listed(self):
        root = self.tree({"dev/f.py": "def f():\n" + "    x = 1\n" * 81})
        self.assertEqual(len(cap_problems(root, {"oversize": {}, "oversize_functions": {}})), 1)
        self.assertEqual(cap_problems(root, {"oversize": {}, "oversize_functions": {"dev/f.py::f": 82}}), [])

    def test_mutable_module_globals(self):
        self.only({"src/taskloop/domain/a.py": "CACHE = {}\n"}, "mutable module global CACHE")
        self.only({"src/taskloop/app/a.py": "from collections import defaultdict\nSEEN = defaultdict(list)\n"}, "SEEN")
        self.only({"src/taskloop/cli/a.py": "_conn = None\n\ndef f():\n    global _conn\n    _conn = 1\n"}, "_conn")
        ok = "from typing import Final\n__all__ = ['A']\nA: Final = ('a',)\nB = (1, 2)\nC: Final[list] = []\nD = None\n"
        self.assertEqual(self.problems({"src/taskloop/domain/a.py": ok}), [])
        self.assertEqual(self.problems({"src/taskloop/adapters/a.py": "CACHE = {}\n"}), [])

    def test_file_names_only_in_contracts_paths(self):
        lit = PATH_LITERALS[0]
        self.assertEqual(self.problems({"src/taskloop/contracts/paths.py": f"A = {lit!r}\n"}), [])
        self.only({"src/taskloop/app/a.py": f"p = root / {lit!r}\n"}, "contracts/paths.py")
        self.assertEqual(self.problems({"src/taskloop/app/a.py": f'"""Writes {lit}."""\n'}), [])


class FolderTable(unittest.TestCase):
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
        edges = {(a, b) for a, bs in ALLOWED.items() for b in bs}
        self.assertIsNone(cycle_in(edges))



# -- tests: the vendored shelf package (dev/vendor.py) ---------------------------------------------------------------------------------
ME = Identity("Vendor Test", "vendor@example.invalid")


class VendorGuard(unittest.TestCase):
    def test_vendor_is_unedited(self):
        self.assertEqual(vendor.problems(None), [], "vendored files edited; change the shelf and run dev/vendor.py sync")

    def test_manifest_lists_the_vendored_package(self):
        entries = vendor.load()
        self.assertEqual(
            [e["name"] for e in entries], sorted(p.name for p in vendor.VENDOR_DIR.iterdir() if p.is_dir() and p.name != "__pycache__")
        )
        for e in entries:
            self.assertEqual(sorted(e), ["name", "shelf_commit", "shelf_tag", "tree_hash"])

    def test_every_vendored_package_imports_by_its_absolute_name(self):
        names = [e["name"] for e in vendor.load()]
        self.assertEqual(
            names, ["atomic_io", "child_env", "git_porcelain", "jsonl_log", "process_lock", "static_page_check", "stream_proc"]
        )
        for name in names:
            with self.subTest(name):
                mod = importlib.import_module(name)
                self.assertEqual(Path(mod.__file__ or "").resolve().parent, (vendor.VENDOR_DIR / name).resolve())
                self.assertEqual(
                    vendor.tree_hash(vendor.dir_files(vendor.VENDOR_DIR / name)),
                    next(e["tree_hash"] for e in vendor.load() if e["name"] == name),
                )

    def test_an_edited_or_added_file_in_any_package_is_drift(self):
        for e in vendor.load():
            with self.subTest(e["name"]):
                files = vendor.dir_files(vendor.VENDOR_DIR / e["name"])
                extra = dict(files, **{"added.py": b"x = 1\n"})
                self.assertNotEqual(vendor.tree_hash(extra), e["tree_hash"])
                first = sorted(files)[0]
                self.assertNotEqual(vendor.tree_hash(dict(files, **{first: files[first] + b"#"})), e["tree_hash"])

    def test_only_the_vendor_dir_is_exempt(self):
        self.assertEqual(EXEMPT_DIRS, ("skills/task-loop/_vendor",))
        self.assertIn(str(ROOT / EXEMPT_DIRS[0]), sys.path)  # importing taskloop put it there

    @real_proc("dev/vendor.py check is the gate's own command line, run against the shelf checkout")
    def test_vendor_drift(self):
        shelf = vendor.shelf_home()
        if not shelf:
            self.skipTest("no shelf checkout ($SHELF_HOME, ../shelf, ~/Workspaces/shelf)")
        r = subprocess.run(
            [sys.executable, str(ROOT / "dev" / "vendor.py"), "check", "--shelf", str(shelf)], capture_output=True, text=True, check=False
        )
        self.assertEqual(r.returncode, 0, r.stderr)


@real_proc("the gate rules run against a real git repo and the fake one: the same answers")
class Smoke(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = hermetic_env(identity=ME, home=self.tmp)
        patcher = mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None})
        patcher.start()
        self.addCleanup(patcher.stop)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)

    def real(self):
        path = self.tmp / "real"
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
        wt = RealRepo(path, identity=ME).worktree(path)
        return wt, lambda rel, text: (wt.path / rel).write_text(text, encoding="utf-8")

    def fake(self):
        repo = FakeRepo.init(self.tmp / "fake")
        wt = repo.worktree(repo.path)
        return wt, wt.write_file

    def scenario(self, make):
        wt, write = make()
        self.assertTrue(wt.health().ok)
        write("a.txt", "1\n")
        first = wt.record("one", paths="all")
        write("a.txt", "2\n")
        snap = wt.snapshot("main")
        self.assertEqual((snap.branch, snap.head), ("main", first.sha))
        self.assertNotEqual(snap.tree, snap.head_tree)
        second = wt.record("two", paths="all")
        self.assertNotEqual(first.sha, second.sha)
        taken = wt.take_branch("work", "main", mode="resume")
        after = wt.snapshot("main")
        self.assertEqual((after.branch, after.head), ("work", second.sha))
        return [e.subject for e in wt.repo.history(["HEAD"], limit=5)], type(taken).__name__

    def test_real_and_fake_answer_the_same(self):
        try:
            real = self.scenario(self.real)
        except GitUnavailable:
            self.skipTest("no git binary")
        self.assertEqual(real, self.scenario(self.fake))
        self.assertEqual(real[0], ["two", "one"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--measure"]:
        print(json.dumps(measure_tree(ROOT), indent=1, sort_keys=True))
    else:
        unittest.main()
