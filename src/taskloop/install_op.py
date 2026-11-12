"""`tl install REV --checkout PATH`: one immutable install of one commit (tl-8bh9.8.3 sections 6.1, 6.4 and 11).

REV is an exactly named annotated tag or a full commit id, read from the person's checkout through `Objects` (a subset
of git_porcelain's `Repo`; read only, no fetch). The install's state is decided only under the install lock
(`installs/<commit>.lock`, `process_lock`, never waited for), by `installs.state`, the rule every reader uses. An absent
install is exported natively from the commit's tree, built by uv (the one external tool, through `Tools`: real
`cli_composition.UvTools` over `stream_proc.run`/`capture`), verified by its own `version --json` and completed by the
manifest, written last by atomic rename. Nothing is ever removed: an interrupted install leaves its own directory without
a manifest, which the next install refuses `incomplete` for the person to check and remove.
"""

import contextlib
import json
import shlex
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

from git_porcelain import GitUnavailable, LogEntry, NotARepo, RefEntry, Tree
from process_lock import LockHeldError, ProcessLock

from taskloop.installs import (
    MANIFEST,
    Manifest,
    Reads,
    Writes,
    atomic_write,
    installs_root,
    is_commit,
    is_tag,
    manifest_text,
    python_of,
    state,
    utc_text,
)
from taskloop.repo import UnsupportedCheckout

LABEL: Final = "taskloop-install"
PACKAGE: Final = "iorlas-task-loop"
LOG: Final = "install.log"
BUILD_SECONDS: Final = 900.0
VERIFY_SECONDS: Final = 60.0
FILE_MODES: Final = {"100644": 0o644, "100755": 0o755}  # 120000 (a symlink) and 160000 (a gitlink) are refused `tree`


class Objects(Protocol):
    """The Git reads of an install: git_porcelain's `Repo.tree`, `Repo.refs` and `Repo.history`."""

    def tree(self, rev: str) -> Tree | None: ...
    def refs(self, prefixes: Sequence[str]) -> tuple[RefEntry, ...]: ...
    def history(self, revs: Sequence[str], *, limit: int | None = None) -> tuple[LogEntry, ...]: ...


@dataclass(frozen=True)
class Ran:
    exit: int | None  # None: a signal ended it
    timed_out: bool
    signal: int | None = None
    survivors: tuple[int, ...] = ()  # processes of uv's tree still alive after it was stopped


@dataclass(frozen=True)
class Answer:
    exit: int
    out: str
    timed_out: bool


class Tools(Protocol):
    """uv on PATH, its build streamed line by line, and the new install's verification answer."""

    def which(self, name: str) -> str | None: ...
    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], line: Callable[[str], None],
            timeout: float) -> Ran: ...
    def capture(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float) -> Answer: ...


class Files(Reads, Writes, Protocol):
    """`installs.state`'s reads and the manifest's atomic write."""


@dataclass(frozen=True)
class Opened:
    checkout: Path
    objects: Objects


@dataclass(frozen=True)
class Ports:
    open_checkout: Callable[[str], Opened]  # raises UnsupportedCheckout, GitUnavailable (NotARepo) or OSError
    tools: Tools
    files: Files
    environ: Mapping[str, str]
    home: Path
    now: Callable[[], datetime]
    say: Callable[[str], None]  # one progress line, or one line of uv's output


@dataclass(frozen=True)
class Source:
    commit: str
    tag: str | None
    tree: Tree


@dataclass(frozen=True)
class Installed:
    install: Path
    manifest: Manifest
    already: bool
    asked: str | None  # the tag name given, None for a commit id


@dataclass(frozen=True)
class Refused:
    word: str
    detail: str


@dataclass(frozen=True)
class Unavailable:
    word: str
    detail: str


type Result = Installed | Refused | Unavailable


def _commit_tree(objects: Objects, rev: str) -> Tree | None:
    """The tree of `rev` when it names a commit; None for nothing, a tree, a blob or a tag of one (no history)."""
    tree = objects.tree(rev)
    if tree is None:
        return None
    first = objects.history([tree.sha], limit=1)
    return tree if first and first[0].sha == tree.sha else None


def resolve(objects: Objects, rev: str) -> Source | Refused:
    """A full commit id of a commit, or a tag named exactly `refs/tags/<rev>` that peels to a commit and whose ref names
    another object than that commit (an annotated tag; by this rule also a lightweight ref to an annotated tag object)."""
    if is_commit(rev):
        tree = _commit_tree(objects, rev)
        return Source(rev, None, tree) if tree is not None and tree.sha == rev else Refused(
            "revision", f"{rev} is not a commit in the checkout")
    if not is_tag(rev):
        return Refused("revision", f"{rev!r} is neither an annotated tag name nor a full commit id")
    ref = f"refs/tags/{rev}"
    named = [entry.sha for entry in objects.refs([ref]) if entry.name == ref]
    if not named:
        return Refused("revision", f"no tag {rev} in the checkout (a branch or short id is not accepted)")
    tree = _commit_tree(objects, ref)
    if tree is None:
        return Refused("revision", f"tag {rev} names no commit")
    if named[0] == tree.sha:
        return Refused("not_annotated", f"tag {rev} is a lightweight tag; an install names an annotated tag or a commit id")
    return Source(tree.sha, rev, tree)


def unsafe(tree: Tree) -> str | None:
    """Why the tree cannot be exported as plain files: a symlink or gitlink; a path with an empty, `.`, `..` or `.git` part
    (any case); two paths, or a file and a folder, that differ only in case (one on a case-insensitive file system)."""
    files: dict[str, str] = {}
    folders: dict[str, str] = {}
    for path, (mode, _) in sorted(tree.files.items()):
        parts = path.split("/")
        if mode not in FILE_MODES:
            return f"{path} has mode {mode} (only regular files are installed)"
        if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts):
            return f"{path!r} is not a safe path"
        folded = path.casefold()
        if folded in files or folded in folders:
            return f"{path!r} differs only in case from {files.get(folded) or folders[folded]!r}"
        files[folded] = path
        folders.update(("/".join(parts[:end]).casefold(), "/".join(parts[:end])) for end in range(1, len(parts)))
    clash = next((path for folded, path in files.items() if folded in folders), None)
    return None if clash is None else f"{clash!r} is a file and, in another case, a folder"


def export(tree: Tree, source: Path) -> int | str:
    """Every file of the tree under `source` with its bytes and mode: their number, or the path Git listed but could not
    read. Raises OSError and GitUnavailable."""
    for path, (mode, _) in sorted(tree.files.items()):
        data = tree.read(path)
        if data is None:
            return path
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(FILE_MODES[mode])
    return len(tree.files)


STRIPPED: Final = frozenset({"VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "GIT_DIR", "GIT_WORK_TREE",
                             "GIT_INDEX_FILE"})


def build_env(environ: Mapping[str, str], venv: Path) -> dict[str, str]:
    """The person's environment without any `UV_*` variable, an active environment, Python's path variables or Git's
    repository variables; plus the install's project environment and `UV_NO_CONFIG` (no `uv.toml` or `[tool.uv]` settings
    from the person's folders; the project's `[tool.uv.sources]` are still read)."""
    kept = {name: value for name, value in environ.items() if not name.startswith("UV_") and name not in STRIPPED}
    return kept | {"UV_PROJECT_ENVIRONMENT": str(venv), "UV_NO_CONFIG": "1"}


def build_argv(uv: str, commit: str) -> list[str]:
    """`--project`, not `--directory`: uv's working directory stays the installs root, so nothing inside the exported
    commit chooses the tools that build it."""
    return [uv, "--project", f"{commit}/source", "sync", "--frozen", "--no-editable", "--no-dev", "--reinstall-package", PACKAGE]


def verified(answer: Answer, venv: Path) -> str | None:
    """None when the answer is `tl version --json` running from `venv`; else why not."""
    if answer.timed_out or answer.exit != 0:
        return f"timed out after {VERIFY_SECONDS:.0f} s" if answer.timed_out else f"exited {answer.exit}"
    try:
        data: object = json.loads(answer.out)
    except ValueError:
        return "the answer is not JSON"
    running = data.get("running") if isinstance(data, dict) else None
    prefix = running.get("prefix") if isinstance(running, dict) else None
    if not isinstance(prefix, str):
        return "the answer has no running.prefix"
    return None if Path(prefix).resolve() == venv.resolve() else f"it runs from {prefix}, not {venv}"


def _recovery(commit: str) -> str:
    return (f"Check that no uv or tl install runs under that path (ps -o pid=,command= -u \"$USER\" | grep {commit[:12]}), "
            "remove the directory, and install again.")


def incomplete(install: Path, commit: str) -> str:
    """The `incomplete` refusal: a directory found without a manifest."""
    return f"{install} has no manifest (an earlier install did not finish). {_recovery(commit)}"


def left(install: Path, commit: str) -> str:
    """What this install leaves when it stops after making its directory."""
    return f"{install} is left without a manifest. {_recovery(commit)}"


def _tell(say: Callable[[str], None], text: str) -> None:
    """A terminal line; a closed terminal (a broken pipe) never stops the install or its log."""
    with contextlib.suppress(OSError):
        say(text)


class _Log:
    """uv's lines to `install.log` first, then the terminal; safe for uv's two output readers. A failed log write is kept
    (`failed`) for the install to report, never silently dropped."""

    def __init__(self, path: Path, say: Callable[[str], None]) -> None:
        self.path, self.say, self.guard = path, say, threading.Lock()
        self.failed: str | None = None

    def line(self, text: str) -> None:
        with self.guard:
            try:
                with self.path.open("a", encoding="utf-8") as log:
                    log.write(text + "\n")
            except OSError as error:
                self.failed = self.failed or f"{self.path}: {type(error).__name__}: {error}"
            _tell(self.say, text)


def _ended(ran: Ran) -> str:
    """How uv ended, and whether its tree may still be writing."""
    how = (f"timed out after {BUILD_SECONDS:.0f} s" if ran.timed_out else f"ended by signal {ran.signal}"
           if ran.exit is None else f"exited {ran.exit}")
    pids = " ".join(str(pid) for pid in ran.survivors)
    return how + (f"; its process tree may still be writing (pids {pids})" if pids else "")


def _sync(uv: str, source: Source, install: Path, root: Path, ports: Ports) -> Refused | Unavailable | None:
    log = _Log(install / LOG, ports.say)
    env, argv = build_env(ports.environ, install / "venv"), build_argv(uv, source.commit)
    log.line(f"Build: {shlex.join(['uv', *argv[1:]])} (log {log.path})")
    try:
        ran = ports.tools.run(argv, cwd=root, env=env, line=log.line, timeout=BUILD_SECONDS)
    except OSError as error:  # uv could not be started (removed or not executable since `which`)
        return Refused("build", f"uv did not start: {type(error).__name__}: {error}; {left(install, source.commit)}")
    if log.failed is not None:
        return Unavailable("write", f"install.log: {log.failed}; {left(install, source.commit)}")
    if ran.timed_out or ran.exit != 0 or ran.survivors:
        last = next((text for text in reversed(log.path.read_text(encoding="utf-8").splitlines()) if text.strip()), "(no output)")
        return Refused("build", f"uv {_ended(ran)}: {last} (log {log.path}); {left(install, source.commit)}")
    return None


def _verify(source: Source, install: Path, root: Path, ports: Ports) -> Refused | None:
    venv, log = install / "venv", install / LOG
    try:
        answer = ports.tools.capture([str(python_of(install)), "-I", "-m", "taskloop", "version", "--json"], cwd=root,
                                     env=build_env(ports.environ, venv), timeout=VERIFY_SECONDS)
    except OSError as error:  # no venv/bin/python to start
        return Refused("verify", f"{type(error).__name__}: {error}; {left(install, source.commit)}")
    with log.open("a", encoding="utf-8") as appended:
        appended.write(f"verify: exit {answer.exit}{' (timed out)' if answer.timed_out else ''}: {answer.out.strip()}\n")
    why = verified(answer, venv)
    if why is not None:
        return Refused("verify", f"{why} (log {log}); {left(install, source.commit)}")
    _tell(ports.say, f"Verify: running from {venv}")
    return None


def _built(uv: str, source: Source, checkout: Path, install: Path, ports: Ports) -> Result:
    """Export, build, verify, then the manifest last; raises OSError, GitUnavailable and KeyboardInterrupt."""
    exported = export(source.tree, install / "source")
    if isinstance(exported, str):
        return Unavailable("git", f"{exported} at {source.commit} is listed but unreadable; {left(install, source.commit)}")
    _tell(ports.say, f"Export: {exported} files to {install / 'source'}")
    stopped = _sync(uv, source, install, install.parent, ports) or _verify(source, install, install.parent, ports)
    if stopped is not None:
        return stopped
    manifest = Manifest(source.commit, source.tag, utc_text(ports.now()), str(checkout))
    atomic_write(ports.files, install / MANIFEST, manifest_text(manifest))
    return Installed(install, manifest, already=False, asked=source.tag)


def _absent(source: Source, checkout: Path, root: Path, ports: Ports) -> Result:
    """Every check that can refuse without writing comes first; once the directory is made, any stop says it is left
    without a manifest and how to remove it."""
    why = unsafe(source.tree)
    if why is not None:
        return Refused("tree", why)
    uv = ports.tools.which("uv")
    if uv is None:
        return Unavailable("uv", "uv is not on PATH")
    install = root / source.commit
    install.mkdir()
    try:
        return _built(uv, source, checkout, install, ports)
    except KeyboardInterrupt:
        return Unavailable("interrupted", left(install, source.commit))
    except GitUnavailable as error:
        return Unavailable("git", f"{error}; {left(install, source.commit)}")
    except OSError as error:
        return Unavailable("write", f"{type(error).__name__}: {error}; {left(install, source.commit)}")


def _locked(source: Source, checkout: Path, root: Path, ports: Ports) -> Result:
    """The install's state, decided under its lock: complete is `already`, broken and incomplete refuse, absent builds."""
    install = root / source.commit
    found = state(ports.files, root, source.commit)
    match found.word:
        case "complete" if found.manifest is not None:
            return Installed(install, found.manifest, already=True, asked=source.tag)
        case "incomplete":
            return Refused("incomplete", incomplete(install, source.commit))
        case "absent":
            return _absent(source, checkout, root, ports)
        case _:
            return Refused("broken", f"{install}: {found.detail}. Check that nothing runs from it (ps), move it aside, and "
                                     "install again.")


def lock(root: Path, commit: str) -> ProcessLock:
    """Take `installs/<commit>.lock` now (never waited for); LockHeldError when another install of it holds it."""
    root.mkdir(parents=True, exist_ok=True)
    return ProcessLock.acquire(root / f"{commit}.lock", timeout=0, label=LABEL, meta={"commit": commit}, reentrant=False)


def _announce(source: Source, checkout: Path) -> str:
    named = source.commit if source.tag is None else f"{source.tag} = {source.commit}"
    return f"Install: {named} ({'commit' if source.tag is None else 'annotated tag'}) from {checkout}"


def _source(rev: str, checkout: str, ports: Ports) -> tuple[Path, Source] | Refused | Unavailable:
    """The checkout and REV's commit, read from Git; nothing written."""
    try:
        opened = ports.open_checkout(checkout)
        source = resolve(opened.objects, rev)
    except (UnsupportedCheckout, NotARepo, OSError) as error:
        return Refused("checkout", str(error))
    except GitUnavailable as error:
        return Unavailable("git", str(error))
    return source if isinstance(source, Refused) else (opened.checkout, source)


def install(rev: str, checkout: str, ports: Ports) -> Result:
    """`tl install REV --checkout PATH`: never pins, removes, or writes the checkout, PATH or another install."""
    found = _source(rev, checkout, ports)
    if not isinstance(found, tuple):
        return found
    path, source = found
    _tell(ports.say, _announce(source, path))
    root = installs_root(ports.home)
    try:
        held = lock(root, source.commit)
    except LockHeldError as error:
        return Refused("busy", f"another tl install of {source.commit[:12]} runs ({error})")
    except OSError as error:
        return Unavailable("write", f"{root}: {type(error).__name__}: {error}")
    try:
        return _locked(source, path, root, ports)
    except GitUnavailable as error:
        return Unavailable("git", str(error))
    except OSError as error:
        return Unavailable("write", f"{type(error).__name__}: {error}")
    finally:
        held.release()
