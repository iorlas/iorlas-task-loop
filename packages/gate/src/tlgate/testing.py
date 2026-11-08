"""Small recording fakes for the capabilities a gate host supplies."""
import shutil
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Literal

import stream_proc
from any_lease import Leases
from tlkernel.argv import text_of
from tlkernel.checks import BaseRedRecord, CheckRun, Durations, PassRecord
from tlkernel.config import EngineConfig, HostResources
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.ids import TreeSha
from tlkernel.log import CmdEnd, CmdStart, EngineLog, Note
from tlkernel.paths import ConfigDir
from tlkernel.procport import Child, Hold, Ran, RanBytes, Streamed
from tlkernel.storeapi import Passes
from tlkernel.waitenums import WaitWhat
from tltestkit.memdoc import MemDoc, MemDocSet
from tltestkit.tmpdir import mkdtemp

from tlgate.checklog import CheckLog


def scalar[T](kind: type[T], value: object) -> T:
    assert isinstance(value, kind), f"expected {kind}: {value!r}"
    return value


def rows[T](kind: type[T], value: object) -> list[T]:
    assert isinstance(value, (list, tuple)), f"expected rows: {value!r}"
    return [scalar(kind, row) for row in value]


class ScriptedGateGit:
    """Keys omit the repository, use method__leading__args, and prefer the longest match.

    Lists supply successive replies; use a tuple for a single file-list answer.
    """

    def __init__(self, **replies: object) -> None:
        self.replies = {tuple(k.split("__")): v for k, v in replies.items()}
        self.calls: list[tuple[str, ...]] = []

    def answer(self, name: str, *args: str) -> object:
        self.calls.append((name, *args))
        for n in range(len(args), -1, -1):
            key = (name, *args[:n])
            if key in self.replies:
                reply = self.replies[key]
                if not isinstance(reply, list):
                    return reply
                if reply:
                    return reply.pop(0)
                break
        raise AssertionError(f"git {name} {' '.join(args)}: no reply scripted")

    def rev_parse(self, d: str, rev: str) -> str:
        return scalar(str, self.answer("rev_parse", rev))

    def merge_base(self, d: str, a: str, b: str) -> str:
        return scalar(str, self.answer("merge_base", a, b))

    def changed_paths(self, d: str, a: str, b: str, *, required: bool = False) -> list[str]:
        return rows(str, self.answer("changed_paths", a, b))

    def ls_files(self, d: str, scope: Literal["tracked", "unignored", "ignored"] = "tracked", *spec: str) -> list[str]:
        return rows(str, self.answer("ls_files", scope, *spec))

    def ls_tree(self, d: str, rev: str, *paths: str, recursive: bool = False) -> list[TreeEntry]:
        return rows(TreeEntry, self.answer("ls_tree", rev, *paths))

    def tree_of(self, d: str) -> str:
        return scalar(str, self.answer("tree_of"))

    def show(self, d: str, rev: str, path: str) -> str:
        return scalar(str, self.answer("show", rev, path))

    def dirty(self, d: str) -> bool:
        return scalar(bool, self.answer("dirty"))

    def common_dir(self, d: str) -> str:
        return scalar(str, self.answer("common_dir"))

    def branch(self, d: str) -> str:
        return scalar(str, self.answer("branch"))

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        self.answer("add_worktree", path, ref)

    def add_worktree_force(self, repo: str, path: str, ref: str) -> None:
        self.answer("add_worktree_force", path, ref)

    def remove_worktree_force(self, repo: str, path: str) -> None:
        self.answer("remove_worktree_force", path)

    def prune_worktrees(self, repo: str) -> None:
        self.answer("prune_worktrees")

    def push(self, d: str, remote: str, refspec: str) -> None:
        self.answer("push", remote, refspec)


class FakeSpawner:
    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
            extra: Mapping[str, str] | None = None, timeout_s: float | None = None, capture: bool = True,
            input: str | None = None) -> Ran:
        if input is not None:
            result = stream_proc.capture_bytes(argv, cwd=cwd, env={**(env or {}), **(extra or {})},
                                               timeout=timeout_s, capture=capture, input=input.encode())
            return Ran(exit=result.exit, out=result.out.decode(), err=result.err.decode(), timed_out=result.timed_out)
        chunks: list[str] = []
        result = self.stream(argv, cwd=cwd, env=env, extra=extra, timeout_s=timeout_s, on_output=chunks.append)
        return Ran(exit=124 if result.timed_out else -(result.signal or 0) or result.returncode or 0,
                   out="".join(chunks), timed_out=bool(result.timed_out))

    def stream(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
               extra: Mapping[str, str] | None = None, on_output: Callable[[str], None], timeout_s: float | None = None,
               stop: threading.Event | None = None, grace: float = 5.0) -> Streamed:
        result = stream_proc.run(argv, cwd=cwd, env={**(env or {}), **(extra or {})}, on_stdout=on_output,
                                 on_stderr=on_output, timeout=timeout_s, stop=stop, grace=grace)
        return Streamed(returncode=result.returncode, signal=result.signal, timed_out=result.timed_out,
                        secs=result.secs, survivors=tuple(result.survivors))

    def run_bytes(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None) -> RanBytes:
        result = stream_proc.capture_bytes(argv, cwd=cwd, env=extra)
        return RanBytes(exit=result.exit, out=result.out, err=result.err)

    def start(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              extra: Mapping[str, str] | None = None, stdin: Literal["null", "pipe"] = "null",
              out: IO[bytes] | Literal["null", "inherit"] = "null") -> Child:
        raise AssertionError("gate must not start detached children")

    def start_held(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
                   extra: Mapping[str, str] | None = None, out: IO[bytes]) -> tuple[Child, Hold]:
        raise AssertionError("gate must not start held children")

    def stop_pid(self, pid: int, start: str | None = None, grace: float = 5.0) -> tuple[int, ...]:
        raise AssertionError("gate must not stop unrelated processes")


class FakeGateLog:
    def __init__(self) -> None:
        self.records: list[EngineLog] = []
        self.ids = 0

    def emit(self, rec: EngineLog) -> int:
        offset = len(self.records)
        self.records.append(rec)
        return offset

    def note(self, text: str) -> int:
        return self.emit(Note(text=text))

    def next_id(self, prefix: str) -> str:
        self.ids += 1
        return f"{prefix}{self.ids}"


class FakeSteps:
    def __init__(self, id: str = "") -> None:
        self.id = id
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def begin(self, step: str, text: str, **meta: object) -> None:
        self.calls.append(("begin", (step, text), meta))

    def outcome(self, outcome: str, detail: str = "") -> None:
        self.calls.append(("outcome", (outcome, detail), {}))


class RecordedWaits:
    """WaitsView: the waits a check reported, kept in a list."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, float]] = []

    def note_slot_waits(self, text: str, wall: float) -> None:
        self.seen.append((text, wall))

    def start(self, what: WaitWhat, holder: str = "", until: float | None = None, track: str = "", check: str = "") -> str:
        return f"w{len(self.seen)}"

    def add(self, secs: float, what: WaitWhat, wid: str | None = None, track: str = "", check: str = "") -> None:
        self.seen.append((what.value, secs))


class FakeGateStores:
    def __init__(self) -> None:
        self._passes: dict[tuple[str, str], MemDocSet[PassRecord]] = {}
        self._reds: dict[str, MemDocSet[BaseRedRecord]] = {}
        self._runs: dict[tuple[str, int | None], MemDoc[CheckRun]] = {}
        self.durations = MemDocSet(Durations)
        self.host = MemDoc(HostResources)
        root = mkdtemp(prefix="tl-leases-")
        self.leases = Leases(Path(root))
        weakref.finalize(self.leases, shutil.rmtree, root, True)

    def results(self, repo: str, check: str) -> Passes:
        return self._passes.setdefault((repo, check), MemDocSet(PassRecord))

    def base_red(self, repo: str) -> MemDocSet[BaseRedRecord]:
        return self._reds.setdefault(repo, MemDocSet(BaseRedRecord))

    def check_run(self, run: str, rnd: int | None) -> MemDoc[CheckRun]:
        return self._runs.setdefault((run, rnd), MemDoc(CheckRun))


class FakeCheckout:
    def __init__(self, tree: TreeSha | None = None, paths: Sequence[str] = ()) -> None:
        self.tree, self.paths = tree if tree is not None else TreeSha("tree"), list(paths)

    def tree_hash(self) -> TreeSha:
        return self.tree

    def changed_paths(self) -> list[str]:
        return list(self.paths)


class FakeTreeWriter:
    def stage_all(self, check: bool = False, everything: bool = False) -> int:
        return 0


class FakeGateHost:
    """A gate host with no engine, repository or real process adapter."""

    def __init__(self, wt: Path, cfg: EngineConfig | None = None, git: ScriptedGateGit | None = None) -> None:
        self.wt, self.cfg, self.git = wt, cfg or EngineConfig(), git or ScriptedGateGit()
        self.bead, self.run_id = "test-bead", "test-run"
        self.run_dir, self.home = wt / "run", ConfigDir(wt / "home")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.env, self.bead_env = Env(), dict[str, str]()
        self.log, self.steps, self.stores, self.waits = FakeGateLog(), FakeSteps(), FakeGateStores(), RecordedWaits()
        self.checklog, self.spawner = CheckLog(self.log), FakeSpawner()
        self.checkout, self.tree_writer = FakeCheckout(), FakeTreeWriter()
        self.killed = self.wall_hit = False
        self.warnings: list[str] = []
        self.details: list[list[str]] = []

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None,
           stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        cid, chunks = self.log.next_id("m"), list[str]()
        self.log.emit(CmdStart(id=cid, text=text_of(cmd), cwd=str(cwd or self.wt)))
        result = self.spawner.stream(list(cmd), cwd=str(cwd or self.wt), env=self.env.vars,
                                     extra={**self.bead_env, **(env or {})}, on_output=chunks.append, timeout_s=timeout, stop=stop)
        self.killed, self.wall_hit = bool(result.timed_out), result.timed_out == "wall"
        rc = 124 if self.wall_hit else -(result.signal or 0) or result.returncode or 0
        output = "".join(chunks)
        if save is not None:
            save.write_text(output)
        tail = "\n".join(output.strip().splitlines()[-15:])
        self.log.emit(CmdEnd(id=cid, exit=rc, exec_seconds=result.secs, out=tail[-600:] if rc else ""))
        if check and rc:
            raise AssertionError(f"command failed: {text_of(cmd)}: {rc}: {tail}")
        return rc, tail

    def warn(self, text: str) -> None:
        self.warnings.append(text)

    def detail(self, lines: list[str]) -> None:
        self.details.append(lines)

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        pass
