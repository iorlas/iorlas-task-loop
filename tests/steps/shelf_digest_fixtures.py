"""Committed-object fakes for digest tests; nothing imports or executes fixture source."""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import override

from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeRepo

from taskloop.shelf_digest.identities import PACKAGES, Identities, IdentityFailure, reconcile_manifests
from taskloop.shelf_digest.installed import Distribution, InstalledDistributions, InstalledMetadata
from taskloop.shelf_digest.source import ReadFailure, open_source

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


@cache
def contract_sources() -> dict[str, bytes]:
    """Use seven pinned installed modules as source data, without executing their code."""
    files = {}
    for package, modules in (
        ("any-agent", ("supervisor", "protocol", "watch", "procs", "events")),
        ("stream-proc", ("registered",)), ("git-porcelain", ("real_write",)),
    ):
        distribution, = InstalledDistributions().find(package)
        for module in modules:
            path = f"{package.replace('-', '_')}/{module}.py"
            data = distribution.read(path)
            assert isinstance(data, bytes)
            files[f"packages/{package}/src/{path}"] = data + b"\n__all__ = ()\n"
    return files


def complete_case(path: Path, *, commit: str = COMMIT, reverse: bool = False, stream_version: str = "1.0") -> Case:
    declarations: list[str] = []
    records: list[str] = []
    metadata: list[str] = []
    files: dict[str, bytes] = {}
    for name in PACKAGES:
        version = stream_version if name == "stream-proc" else "1.0"
        tag = f"{'any-agent' if name == 'stream-proc' else name}-v1.0"
        directory = f"packages/{name}"
        selector = f"{URL}?tag={tag}&subdirectory={directory}"
        declarations.append(f'{name} = {{git = "{URL}", subdirectory = "{directory}", tag = "{tag}"}}')
        records.append(f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{git = "{selector}#{commit}"}}')
        metadata.append(f'{{name = "{name}", git = "{selector}"}}')
        files[f"{directory}/pyproject.toml"] = f'[project]\nname = "{name}"\nversion = "{version}"'.encode()
        module = name.replace("-", "_")
        files[f"{directory}/src/{module}/__init__.py"] = b'"""Module warning."""\nVALUE = 1\n'
        files[f"{directory}/README.md"] = f"# {name}\n\nOnly valid when idle.\n\nExample: café\n".encode()
    files.update(contract_sources())
    dependencies = ", ".join(f'"{name}=={stream_version if name == "stream-proc" else "1.0"}"' for name in PACKAGES)
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


@dataclass
class MemoryDistribution:
    record: InstalledMetadata
    contents: dict[str, bytes | ReadFailure]
    reads: list[str] = field(default_factory=list)

    def metadata(self) -> InstalledMetadata:
        return self.record

    def files(self) -> tuple[str, ...]:
        return tuple(self.contents)

    def read(self, path: str) -> bytes | ReadFailure:
        self.reads.append(path)
        return self.contents[path]


@dataclass
class MemoryDistributions:
    records: dict[str, MemoryDistribution]
    duplicates: tuple[str, ...] = ()

    def find(self, name: str) -> tuple[Distribution, ...]:
        if name not in self.records:
            return ()
        record = self.records[name]
        return (record, record) if name in self.duplicates else (record,)


def installed_case(case: Case) -> tuple[Identities, MemoryDistributions]:
    source = open_source(case.root, SOURCE_COMMIT)
    assert not isinstance(source, ReadFailure)
    identities = reconcile_manifests(source)
    assert not isinstance(identities, (IdentityFailure, ReadFailure))
    distributions: dict[str, MemoryDistribution] = {}
    for identity in identities.packages:
        record = InstalledMetadata(name=identity.name, version=identity.version, direct_url=json.dumps({
            "url": identity.repository_url, "subdirectory": identity.subdirectory,
            "vcs_info": {"vcs": "git", "commit_id": identity.commit, "requested_revision": identity.requested_tag},
        }))
        prefix = f"{identity.subdirectory}/"
        files: dict[str, bytes | ReadFailure] = {
            path.removeprefix(prefix).removeprefix("src/"): data
            for path, data in case.shelf_files.items() if path.startswith(prefix) and not path.endswith("pyproject.toml")
        }
        distributions[identity.name] = MemoryDistribution(record, files)
    return identities, MemoryDistributions(distributions)
