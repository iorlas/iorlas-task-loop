"""Installs and pins made on a home under tmp_path, through the real writers; file ports that refuse one read or write;
a repository's objects (`TagRepo`) and uv (`FakeTools`) for `install_op`."""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from git_porcelain import LogEntry, MissingRevision, RefEntry, Sha, Tree

from taskloop import pin_file
from taskloop.install_op import Answer, Opened, Ports, Ran
from taskloop.installs import MANIFEST, Kind, LocalFiles, Manifest, atomic_write, installs_root, manifest_text, python_of

A: Final = "3f2a9c4e1b07" + "a" * 28
B: Final = "9b1e07d2aa31" + "b" * 28
NOW: Final = datetime(2026, 11, 20, 10, 5, tzinfo=UTC)


def make_install(home: Path, commit: str, tag: str | None = None, *, manifest: str | None = None) -> Path:
    """`installs/<commit>/` with an executable `venv/bin/python` and the manifest the writer formats (or `manifest`)."""
    install = installs_root(home) / commit
    python = python_of(install)
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    text = manifest_text(Manifest(commit, tag, "2026-11-20T10:00:00Z", "/home/u/src/task-loop")) if manifest is None else manifest
    atomic_write(LocalFiles(), install / MANIFEST, text)
    return install


def make_pin(home: Path, commit: str, tag: str | None = None, config: str | None = None) -> Path:
    path = pin_file.pin_path(config, home)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    pin_file.write(LocalFiles(), path, commit, tag, NOW)
    return path


class Refusing(LocalFiles):
    """The local files, except that reading `unreadable` raises, `unexaminable` cannot be examined, and the named write
    step (`write`: after half the bytes; `replace`) raises OSError."""

    def __init__(self, unreadable: Path | None = None, failing: str = "", unexaminable: Path | None = None) -> None:
        self.unreadable = unreadable
        self.failing = failing
        self.unexaminable = unexaminable

    def read_text(self, path: Path) -> str:
        if path == self.unreadable:
            raise PermissionError(13, "Permission denied", str(path))
        return super().read_text(path)

    def kind(self, path: Path) -> Kind:
        return "unexaminable" if path == self.unexaminable else super().kind(path)

    def fill(self, descriptor: int, data: bytes) -> None:
        if self.failing == "write":
            super().fill(descriptor, data[: len(data) // 2])
            raise OSError(28, "No space left on device")
        super().fill(descriptor, data)

    def replace(self, source: Path, target: Path) -> None:
        if self.failing == "replace":
            raise OSError(5, "Input/output error", str(target))
        super().replace(source, target)


def object_id(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


type Files = dict[str, tuple[str, bytes]]  # path -> (mode, bytes)


class TagRepo:
    """A repository's objects as `install_op.Objects` reads them (read only): commits with their files and modes, trees,
    blobs, tag objects naming a commit, a tree or another tag, and refs. `tree` peels a ref or id to its commit or tree as
    `rev^{commit}`, then `rev^{tree}` does (a blob is None); `history` of a tree is empty, as `git log <tree>` is; `refs`
    lists every ref starting with a prefix, in reverse order (so `refs/tags/v1` also lists `refs/tags/v1-rc`, first); reads
    are counted and `on_read` may act before one answers."""

    def __init__(self) -> None:
        self.commits: dict[str, Files] = {}
        self.trees: dict[str, Files] = {}
        self.blobs: set[str] = set()
        self.tags: dict[str, str] = {}  # tag object id -> the object it names
        self.named: dict[str, str] = {}  # full ref name -> object id
        self.unreadable: set[str] = set()
        self.reads: list[str] = []
        self.on_read: Callable[[int], None] | None = None  # told the number of each read before it answers

    def commit(self, name: str, files: Files) -> str:
        commit, tree = object_id(f"commit {name}"), object_id(f"tree {name}")
        self.commits[commit], self.trees[tree] = files, files
        self.blobs.update(object_id(f"blob {path}") for path in files)
        return commit

    def tree_of(self, commit: str) -> str:
        return next(tree for tree, files in self.trees.items() if files is self.commits[commit])

    def annotate(self, name: str, target: str) -> str:
        tag = object_id(f"tag {name} {target}")
        self.tags[tag], self.named[f"refs/tags/{name}"] = target, tag
        return tag

    def _peeled(self, rev: str) -> str:
        found = self.named.get(rev, rev)
        while found in self.tags:
            found = self.tags[found]
        return found

    def tree(self, rev: str) -> Tree | None:
        found = self._peeled(rev)
        files = self.commits.get(found, self.trees.get(found))
        if files is None:
            return None
        listed = {path: (mode, Sha(object_id(f"blob {path}"))) for path, (mode, _) in files.items()}
        return Tree(Sha(found), lambda: listed, lambda path: self._read(files, path))

    def _read(self, files: Files, path: str) -> bytes | None:
        self.reads.append(path)
        if self.on_read is not None:
            self.on_read(len(self.reads))
        return None if path in self.unreadable or path not in files else files[path][1]

    def history(self, revs: Sequence[str], *, limit: int | None = None) -> tuple[LogEntry, ...]:
        found = self._peeled(revs[0])
        if found not in self.commits and found not in self.trees and found not in self.tags:
            raise MissingRevision(f"bad revision {revs[0]}")
        return (LogEntry(Sha(found), 0, "subject", "", None),)[:limit] if found in self.commits else ()

    def refs(self, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
        rows = sorted(self.named.items(), reverse=True)  # not sorted as Git lists them: only the exact name may count
        return tuple(RefEntry(name, Sha(oid)) for name, oid in rows if any(name.startswith(p) for p in prefixes))


def answer_of(python: str) -> Answer:
    """What `<venv>/bin/python -I -m taskloop version --json` of an unpinned new install says: its own prefix."""
    return Answer(0, json.dumps({"running": {"prefix": str(Path(python).parent.parent), "install": None, "tag": None},
                                 "pinned": None}) + "\n", timed_out=False)


@dataclass
class FakeTools:
    """uv found at `uv` (None: not on PATH). `run` records its call, says `lines`, then (unless `raises`) makes the
    project environment's `bin/python` as uv would when it exits 0, and answers `ran`; `capture` records its call and
    answers `answer` (default: the python's own prefix, `answer_of`). `before` acts on the install folder first."""

    uv: str | None = "/opt/uv/bin/uv"
    ran: Ran = field(default_factory=lambda: Ran(0, timed_out=False))
    lines: tuple[str, ...] = ("Resolved 12 packages", "Installed 12 packages")
    raises: BaseException | None = None
    answer: Answer | None = None
    before: Callable[[Path], None] | None = None
    runs: list[tuple[list[str], Path, dict[str, str]]] = field(default_factory=list)
    captures: list[tuple[list[str], Path]] = field(default_factory=list)

    def which(self, name: str) -> str | None:
        assert name == "uv"
        return self.uv

    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], line: Callable[[str], None], timeout: float) -> Ran:
        assert timeout == 900
        self.runs.append((list(argv), cwd, dict(env)))
        if self.before is not None:
            self.before(Path(env["UV_PROJECT_ENVIRONMENT"]).parent)
        for text in self.lines:
            line(text)
        if self.raises is not None:
            raise self.raises
        if self.ran.exit == 0 and not self.ran.timed_out:
            python = Path(env["UV_PROJECT_ENVIRONMENT"]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n")
            python.chmod(0o755)
        return self.ran

    def capture(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float) -> Answer:
        assert timeout == 60 and "UV_PROJECT_ENVIRONMENT" in env
        self.captures.append((list(argv), cwd))
        return answer_of(argv[0]) if self.answer is None else self.answer


CHECKOUT: Final = Path("/home/u/src/task-loop")
ENVIRON: Final = {"PATH": "/usr/bin", "HOME": "/home/u", "UV_CACHE_DIR": "/c", "UV_INDEX_URL": "https://i", "VIRTUAL_ENV": "/v",
                   "CONDA_PREFIX": "/conda", "PYTHONPATH": "/p", "PYTHONHOME": "/h", "PYTHONSTARTUP": "/s", "GIT_DIR": "/g",
                   "GIT_WORK_TREE": "/w", "GIT_INDEX_FILE": "/i"}


def install_ports(home: Path, repo: TagRepo | Exception, tools: FakeTools, said: list[str], files: LocalFiles | None = None,
                  say: Callable[[str], None] | None = None) -> Ports:
    """The operation's ports over the fakes: the checkout opens `repo` (or raises it), the clock reads NOW."""

    def opened(path: str) -> Opened:
        if isinstance(repo, Exception):
            raise repo
        assert path == str(CHECKOUT)
        return Opened(CHECKOUT, repo)

    return Ports(opened, tools, LocalFiles() if files is None else files, ENVIRON, home, lambda: NOW,
                 said.append if say is None else say)
