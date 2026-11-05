"""Which tests a change can break: the files a diff changed, followed up the import graph to the test files that reach them.

    python3 dev/affected.py [--base REV [--head REV]] [--root DIR] [--changed PATH ...]    prints the test files, one per line
    python3 dev/affected.py ... --closure                                                    prints the files those tests depend on instead

The changed files are the diff against BASE (default: the merge base of HEAD and origin/main; no origin/main: HEAD), the working tree
and the untracked files included, or exactly the PATHs given with --changed. The graph is read from the syntax trees under `--root`
(default: this checkout) and never by importing anything. Standard library only; it knows nothing of the project it sits in.

The rules, all in this file, none of them stored or switchable:
  graph       a node is a Python file under src/, tests/, dev/, skills/task-loop/ and its _vendor/ (the vendored packages); an edge is
              an import (lazy and TYPE_CHECKING ones too). A name resolves in the importer's roots, first hit wins
              (a test sees tests/, dev/, src/, the
              vendored packages; src sees src/ and the vendored packages). The tests that run are the test files in the reverse transitive
              closure of the changed files; a changed test file selects itself.
  strings     a Python file whose string constants name a changed file (its basename: "tl.py", "vendor.json") depends on it. This is how a
              test that runs a script by path, or reads a data file, is tied to it; a changed data file reaches tests only this way.
  directories a data file under tests/<dir>/ selects tests/<dir>; under tests/fixtures/<dir>/ it selects tests/<dir> when that exists.
  discovery   a module that lists the modules of a package at run time (pkgutil.iter_modules, walk_packages, importlib.import_module of a
              computed name) depends on every file under each package it imports. A new record module reaches the test that asks every
              record module for a sample this way.
  conftest    pytest loads a conftest.py around every test under its directory, nothing imports it: a changed conftest, or a helper it
              imports
              from tests/, selects every test under that directory. Its imports of src/ and dev/ are ignored (they only warm the process).
  config      pyproject.toml, uv.lock, mise.toml, mise.lock select tests/rules and tests/release; .importlinter, ruff.toml, pyrefly.toml and
              the justfile select tests/rules.
  deleted     a deleted src/taskloop file has no node left to follow: it selects the tests/ folder that mirrors its slice.
  always      tests/rules (they read the whole tree and take seconds), so a change that selects nothing else still runs them.
tests/live is explicit-only and is never selected. There is no flag for a wider run: the full run is `just test-full`.
"""
import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from importgraph import bindings, qualified, targets_of

ROOTS = {"src": "src", "tests": "tests", "dev": "dev", "vendor": "skills/task-loop/_vendor", "tl": "skills/task-loop"}
VISIBLE = {"src": ("src", "vendor"), "tests": ("tests", "dev", "src", "vendor"), "dev": ("dev", "src", "vendor"), "vendor": ("vendor",),
           "tl": ("src", "vendor")}
CONFIG = {"pyproject.toml": ("tests/rules", "tests/release"), "uv.lock": ("tests/rules", "tests/release"),
          "mise.toml": ("tests/rules", "tests/release"), "mise.lock": ("tests/rules", "tests/release"),
          ".importlinter": ("tests/rules",), "ruff.toml": ("tests/rules",), "pyrefly.toml": ("tests/rules",), "justfile": ("tests/rules",)}
ALWAYS = "tests/rules"
DISCOVERY = frozenset({"pkgutil.iter_modules", "pkgutil.walk_packages", "importlib.import_module"})
SKIP_PARTS = frozenset({"__pycache__", ".venv", ".git", "node_modules"})


def git(root, *argv):
    done = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else None


def base_of(root, base=None):
    """`base`, else the merge base of HEAD and origin/main, else HEAD."""
    if base:
        return base
    merged = git(root, "merge-base", "HEAD", "origin/main")
    return merged.strip() if merged else "HEAD"


def changed_files(root, base, head=None):
    """Paths (relative, posix) that differ from `base`: to `head` when given, else the working tree and the untracked files."""
    out = set((git(root, "diff", "--name-only", "--no-renames", base, *([head] if head else [])) or "").split())
    if not head:
        out |= set((git(root, "ls-files", "--others", "--exclude-standard") or "").split())
    return out


class Repo:
    """The Python files of a checkout, their import edges and the strings they mention."""

    def __init__(self, root):
        self.root = Path(root)
        self.trees = {}     # relative path -> (root key, ast.Module)
        self.names = {key: {} for key in ROOTS}      # root key -> importable dotted name -> relative path
        self.packages = {key: set() for key in ROOTS}
        self.nodes = {}
        self.module = {}    # relative path -> dotted name in its root
        self.mentions = {}  # relative path -> basenames of its string constants
        for key, folder in ROOTS.items():
            self.scan(key, folder)
        self.edges = defaultdict(set)
        for path, (key, tree) in self.trees.items():
            self.edges[path] = self.imports_of(path, key, tree)
        self.link_discovery()

    def scan(self, key, folder):
        base = self.root / folder
        for file in sorted(base.rglob("*.py")) if base.is_dir() else ():
            parts = file.relative_to(base).with_suffix("").parts
            if SKIP_PARTS & set(file.parts) or (key == "tl" and parts[0] == "_vendor"):
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, ValueError):
                continue  # a fixture that is broken on purpose: no edges, no mentions
            rel = file.relative_to(self.root).as_posix()
            package = parts[-1] == "__init__"
            name = ".".join(parts[:-1] if package else parts)
            if name:
                self.names[key][name] = rel
                if package:
                    self.packages[key].add(name)
            self.trees[rel] = (key, tree)
            nodes = self.nodes[rel] = list(ast.walk(tree))
            self.module[rel] = name or rel
            self.mentions[rel] = {s.rsplit("/", 1)[-1] for s in strings_of(nodes)}

    def imports_of(self, path, key, tree):
        found = set()
        packages = self.packages[key]
        for target in targets_of(self.module[path], tree, packages, self.nodes[path]):
            parts = target.split(".")
            prefixes = [".".join(parts[:end]) for end in range(1, len(parts) + 1)]
            for visible in VISIBLE[key]:
                hits = {self.names[visible][p] for p in prefixes if p in self.names[visible]}
                if hits:
                    found |= hits
                    break
        found.discard(path)
        if path.endswith("conftest.py"):
            found = {p for p in found if self.trees[p][0] == "tests"}
        return found

    def link_discovery(self):
        """A module that lists a package's modules at run time depends on all of them."""
        for path in self.trees:
            if path.endswith("conftest.py") or not discovers(self.module[path], self.nodes[path]):
                continue
            for target in list(self.edges[path]):
                if target.endswith("__init__.py"):
                    folder = target[: -len("__init__.py")]
                    self.edges[path] |= {p for p in self.trees if p.startswith(folder) and p != path}

    def importers(self):
        back = defaultdict(set)
        for path, targets in self.edges.items():
            for target in targets:
                back[target].add(path)
        return back


def strings_of(nodes):
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200]


def discovers(module, nodes):
    names = bindings(module, None, nodes=nodes)
    for node in nodes:
        if isinstance(node, ast.Call):
            called = qualified(node.func, names)
            literal = node.args and isinstance(node.args[0], ast.Constant)
            if called in DISCOVERY and not (called == "importlib.import_module" and literal):
                return True
    return False


def is_test(path):
    parts = path.split("/")
    return parts[0] == "tests" and parts[1:2] != ["live"] and (parts[-1].startswith("test_") or path == "tests/rules/gate_rules.py") \
        and path.endswith(".py")


def under(repo, folder):
    return {p for p in repo.trees if is_test(p) and p.startswith(folder.rstrip("/") + "/")}


def data_dependents(repo, path):
    """The Python files and test folders a changed non-Python file reaches."""
    file = Path(path)
    hit = {p for p, said in repo.mentions.items() if file.name in said}
    parts = file.parts
    if parts[0] == "tests" and len(parts) > 2:
        folder = parts[2] if parts[1] == "fixtures" and len(parts) > 3 else parts[1]
        if folder != "fixtures":
            hit |= under(repo, f"tests/{folder}")
        if parts[1] == "fixtures":
            hit |= {p for p, said in repo.mentions.items() if file.parent.name in said and is_test(p)}
    return hit


def deleted_slice(repo, path):
    parts = path.split("/")
    if parts[:2] != ["src", "taskloop"] or len(parts) < 4:
        return set()
    return under(repo, f"tests/{parts[3] if parts[2] == 'app' and len(parts) > 4 else parts[2]}")


def seeds(repo, changed):
    """The files the closure starts from, and the folders the config and deleted-file rules add."""
    start, extra = set(), set()
    for path in changed:
        exists = (repo.root / path).exists()
        if path in repo.trees:
            start |= {path} | ({p for p, said in repo.mentions.items() if Path(path).name in said} if not is_test(path) else set())
        elif path.endswith(".py") and not exists:
            extra |= deleted_slice(repo, path)
        elif exists:
            start |= data_dependents(repo, path)
        for folder in CONFIG.get(Path(path).name, ()):
            extra |= under(repo, folder)
    return start, extra


def select(repo, changed):
    """The sorted test files `changed` can break."""
    start, extra = seeds(repo, changed)
    back = repo.importers()
    reached, todo = set(start), list(start)
    while todo:
        for parent in back.get(todo.pop(), ()):
            if parent not in reached:
                reached.add(parent)
                todo.append(parent)
    chosen = {p for p in reached if is_test(p)} | extra | under(repo, ALWAYS)
    for path in reached:
        if path.endswith("conftest.py"):
            chosen |= under(repo, path.rsplit("/", 1)[0])
    return sorted(chosen)


CONFIG_FILES = ("pyproject.toml", "uv.lock", "mise.toml", "mise.lock", ".importlinter", "ruff.toml", "pyrefly.toml", "justfile", ".task-loop.json")


def closure(repo, tests, tracked=None):
    """Every file the result of running `tests` can depend on, sorted: the tests (those of the always-run tests/rules folder left out: they
    read the whole tree and are a check of their own), the conftest.py above each, everything they import (forward, lazy imports too), every
    non-Python file under tests/ and every one a reached file names by basename, and the root config files. Deliberately wide: a file
    in the closure that did not matter costs a rerun, a file that mattered and is missing is a wrong pass."""
    tests = [t for t in tests if not t.startswith(ALWAYS + "/")]
    reached = set(tests)
    for t in tests:
        parts = t.split("/")
        reached |= {c for c in ("/".join(parts[:i] + ["conftest.py"]) for i in range(1, len(parts))) if c in repo.trees}
    todo = list(reached)
    while todo:
        for target in repo.edges.get(todo.pop(), ()):
            if target not in reached:
                reached.add(target)
                todo.append(target)
    named = set().union(*(repo.mentions.get(p, set()) for p in reached)) if reached else set()
    if tracked is None:
        listed = git(repo.root, "ls-files")
        tracked = listed.split("\n") if listed is not None else [p.relative_to(repo.root).as_posix() for p in repo.root.rglob("*")]
    data = {p for p in tracked if p and not p.endswith(".py") and not SKIP_PARTS & set(p.split("/"))
            and (p.startswith("tests/") or Path(p).name in named or p in CONFIG_FILES)}
    return sorted(p for p in reached | data if (repo.root / p).is_file())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="affected.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the checkout to read (default: this one)")
    ap.add_argument("--base", help="the revision to diff against (default: merge base of HEAD and origin/main)")
    ap.add_argument("--head", help="diff BASE..HEAD instead of BASE and the working tree")
    ap.add_argument("--changed", nargs="*", help="exactly these paths, no git")
    ap.add_argument("--closure", action="store_true", help="print the files the selected tests can depend on, not the tests")
    args = ap.parse_args(argv)
    changed = set(args.changed) if args.changed is not None else changed_files(args.root, base_of(args.root, args.base), args.head)
    repo = Repo(args.root)
    chosen = select(repo, changed)
    print("\n".join(closure(repo, chosen) if args.closure else chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
