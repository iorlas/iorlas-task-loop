"""Committed-object fakes for digest tests; nothing imports or executes fixture source."""

from dataclasses import dataclass
from pathlib import Path
from typing import override

from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeRepo

from taskloop.shelf_digest.identities import PACKAGES

COMMIT = "a" * 40
SOURCE_COMMIT = "b" * 40
URL = "https://example.invalid/shelf.git"


class Objects(FakeRepo):
    trees: dict[str, Tree]

    @override
    def tree(self, rev: str) -> Tree | None:
        return self.trees.get(rev.removesuffix("^{commit}"))


def objects(path: Path, commits: dict[str, dict[str, bytes]]) -> Objects:
    repo = Objects.init(path)
    repo.trees = {
        commit: Tree(Sha(commit), lambda files=files: {name: ("100644", Sha("c" * 40)) for name in files}, files.get)
        for commit, files in commits.items()
    }
    return repo


@dataclass(frozen=True)
class Case:
    root: Objects
    shelf: Objects
    shelf_files: dict[str, bytes]


def complete_case(path: Path, *, commit: str = COMMIT, reverse: bool = False) -> Case:
    declarations: list[str] = []
    records: list[str] = []
    metadata: list[str] = []
    files: dict[str, bytes] = {}
    for name in PACKAGES:
        tag = f"{'any-agent' if name == 'stream-proc' else name}-v1.0"
        directory = f"packages/{name}"
        selector = f"{URL}?tag={tag}&subdirectory={directory}"
        declarations.append(f'{name} = {{git = "{URL}", subdirectory = "{directory}", tag = "{tag}"}}')
        records.append(f'[[package]]\nname = "{name}"\nversion = "1.0"\nsource = {{git = "{selector}#{commit}"}}')
        metadata.append(f'{{name = "{name}", git = "{selector}"}}')
        files[f"{directory}/pyproject.toml"] = f'[project]\nname = "{name}"\nversion = "1.0"'.encode()
        module = name.replace("-", "_")
        files[f"{directory}/src/{module}/__init__.py"] = b'"""Module warning."""\nVALUE = 1\n'
        files[f"{directory}/README.md"] = f"# {name}\n\nOnly valid when idle.\n\nExample: café\n".encode()
    dependencies = ", ".join(f'"{name}==1.0"' for name in PACKAGES)
    project = f'[project]\nname = "task-loop"\nversion = "0.1"\ndependencies = [{dependencies}]\n'
    project += '[tool.uv.sources]\n' + "\n".join(declarations)
    root = ('[[package]]\nname = "task-loop"\nversion = "0.1"\nsource = {editable = "."}\n'
            'dependencies = [' + ", ".join(f'{{name = "{name}"}}' for name in PACKAGES) + ']\n'
            '[package.metadata]\nrequires-dist = [' + ", ".join(metadata) + "]")
    root_files = {"pyproject.toml": project.encode(), "uv.lock": "\n".join([*records, root]).encode()}
    if reverse:
        files = dict(reversed(list(files.items())))
        root_files = dict(reversed(list(root_files.items())))
    return Case(objects(path / "root", {SOURCE_COMMIT: root_files}), objects(path / "shelf", {commit: files}), files)
