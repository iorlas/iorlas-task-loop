"""Select tests by reverse Python import reachability, using shelf for Git reads."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
import tomllib
from collections import defaultdict
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest
from git_porcelain import GitError, RealRepo, Worktree
from pydantic import BaseModel, Field


class PytestConfig(BaseModel):
    testpaths: list[str]
    pythonpath: list[str] = Field(default_factory=list)
    python_files: list[str] = Field(default_factory=lambda: ["test_*.py", "*_test.py"])


def changed_paths(worktree: Worktree, base: str = "HEAD") -> frozenset[str]:
    """Union committed, staged, unstaged and untracked paths; let read failures propagate."""
    diff = worktree.diff(base, "HEAD", cap=0)
    dirty = worktree.dirty()
    return frozenset(Path(path).as_posix() for path in (*[change.path for change in diff.changes], *dirty.tracked, *dirty.untracked))


def module_name(path: Path, base: Path) -> str:
    parts = path.relative_to(base).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def documentation(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".rst"} and (path.parts[0] == "docs" or len(path.parts) == 1)


class ImportGraph:
    """Filesystem module identities and dependency edges; never execute an import."""

    def __init__(self, root: Path, config: PytestConfig, changed: set[Path]) -> None:
        self.root = root
        self.bases = [root / "src", root, *(root / path for path in config.pythonpath)]
        folders = [root / "src", *(root / path for path in (*config.testpaths, *config.pythonpath))]
        self.files = {path for folder in folders if folder.is_dir() for path in folder.rglob("*.py")}
        self.files.update(root.glob("*.py"))
        # Parent conftests apply even outside the configured test roots.
        for folder in folders:
            self.files.update(parent / "conftest.py" for parent in (folder, *folder.parents)
                              if parent.is_relative_to(root) and (parent / "conftest.py").is_file())
        self.modules: dict[str, set[Path]] = defaultdict(set)
        self.names: dict[Path, str] = {}
        for path in sorted(self.files | changed):
            for base in self.bases:
                if path.is_relative_to(base):
                    name = module_name(path, base)
                    self.modules[name].add(path)
                    self.names.setdefault(path, name)
        for name in tuple(self.modules):
            parts = name.split(".")
            for end in range(1, len(parts)):
                self.modules.setdefault(".".join(parts[:end]), set())
        self.reverse: dict[Path, set[Path]] = defaultdict(set)
        self.external = set(sys.stdlib_module_names) | set(packages_distributions())
        self.unsafe = False

    def depend(self, consumer: Path, name: str, *, required: bool = True) -> None:
        parts = name.split(".")
        for end in range(1, len(parts) + 1):
            for dependency in self.modules.get(".".join(parts[:end]), ()):
                self.reverse[dependency].add(consumer)
        local = parts[0] in self.modules or any(key.startswith(parts[0] + ".") for key in self.modules)
        if required and name not in self.modules and (local or parts[0] not in self.external):
            self.unsafe = True

    def from_import(self, path: Path, node: ast.ImportFrom, package: str, dynamic: set[str]) -> None:
        prefix = package.split(".") if package else []
        if node.level:
            if node.level > len(prefix):
                self.unsafe = True
            prefix = prefix[:len(prefix) - node.level + 1]
        else:
            prefix = []
        target = ".".join([*prefix, *([node.module] if node.module else [])])
        self.depend(path, target)
        for alias in node.names:
            self.depend(path, f"{target}.{alias.name}", required=False)
            if (target, alias.name) in {("importlib", "import_module"), ("builtins", "__import__")}:
                dynamic.add(alias.asname or alias.name)

    def dynamic_imports(self, path: Path, tree: ast.Module, dynamic: set[str], importlibs: set[str]) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if called in {"spec_from_file_location", "SourceFileLoader", "SourcelessFileLoader", "run_path"}:
                self.unsafe = True
            is_dynamic = isinstance(func, ast.Name) and func.id in dynamic
            is_dynamic |= (isinstance(func, ast.Attribute) and func.attr == "import_module"
                           and isinstance(func.value, ast.Name) and func.value.id in importlibs)
            if is_dynamic:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    target = node.args[0].value
                    if target.startswith("."):
                        self.unsafe = True
                    else:
                        self.depend(path, target)
                else:
                    self.unsafe = True

    def imports(self, path: Path, tree: ast.Module) -> None:
        name = self.names[path]
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        dynamic = {"__import__", "import_module"}
        importlibs = {"importlib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.depend(path, alias.name)
                    if alias.name == "importlib":
                        importlibs.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.from_import(path, node, package, dynamic)
        self.dynamic_imports(path, tree, dynamic, importlibs)

    def build(self) -> None:
        for path in sorted(self.files):
            try:
                self.imports(path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            except (OSError, SyntaxError, UnicodeError):
                self.unsafe = True
            # Importing any module also executes the containing package initializers.
            for parent in path.parents:
                if parent == self.root:
                    break
                initializer = parent / "__init__.py"
                if initializer in self.files:
                    self.reverse[initializer].add(path)
            for conftest in self.files:
                if conftest.name == "conftest.py" and path.is_relative_to(conftest.parent):
                    self.reverse[conftest].add(path)


def select_tests(root: Path, changed: frozenset[str]) -> tuple[Path, ...]:
    """Return sorted existing test paths, widening rather than silently missing dependencies."""
    raw = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    config = PytestConfig.model_validate(raw["tool"]["pytest"]["ini_options"])
    tests = {path for folder in config.testpaths for path in (root / folder).rglob("*.py")
             if any(fnmatch.fnmatch(path.name, pattern) for pattern in config.python_files)}
    paths = {Path(path) for path in changed if not documentation(Path(path))}
    all_tests = tuple(sorted(tests))
    if not paths:
        return ()
    if any(path.is_absolute() or ".." in path.parts or path.suffix != ".py" for path in paths):
        return all_tests
    absolute = {root / path for path in paths}
    graph = ImportGraph(root, config, absolute)
    if not absolute <= graph.files | {path for path in absolute if not path.exists() and path.is_relative_to(root / "src")}:
        return all_tests
    graph.build()
    if graph.unsafe:
        return all_tests
    reached = set(absolute)
    pending = list(absolute)
    while pending:
        for consumer in graph.reverse[pending.pop()] - reached:
            reached.add(consumer)
            pending.append(consumer)
    return tuple(sorted(tests & reached))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="compare this tree-ish to HEAD, in addition to local changes")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        worktree = RealRepo(root, memoize=False, read_timeout=30).worktree(root)
        selected = select_tests(root, changed_paths(worktree, args.base))
    except (GitError, OSError, ValueError, KeyError) as error:
        print(f"Cannot select affected tests: {error}", file=sys.stderr)
        return 1
    if not selected:
        print("No affected tests.")
        return 0
    return int(pytest.main([str(path) for path in selected]))


if __name__ == "__main__":
    raise SystemExit(main())
