"""Moving to a newer install between steps (tl-7y6.9): by exec only, no module is ever reloaded in place. The notes a run leaves for
the process that takes it over: the exec hand-over, the network pause, and the argv that goes on from the checkpoint."""
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jsonl_log import close_held
from tlkernel import rundocs
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.run import NetPause, Reexec, ReexecNote, RunCounters
from tlkernel.waitrows import NET_PAUSE, REEXEC, WaitDoc

NET_PAUSE_ADOPT_S = 21600  # a run paused for the network is taken up again by the next run-task within this long


def reexec_store(home: ConfigDir, bead: BeadId) -> WaitDoc[ReexecNote]:
    return WaitDoc(home, REEXEC, bead, ReexecNote)


def net_pause_store(home: ConfigDir, bead: BeadId) -> WaitDoc[NetPause]:
    return WaitDoc(home, NET_PAUSE, bead, NetPause)


def read_reexec(home: ConfigDir, bead: BeadId) -> ReexecNote | None:
    """The note an engine leaves just before it execs into a newer install; None when none (or not of this version)."""
    return reexec_store(home, bead).get()


def drop_reexec(home: ConfigDir, bead: BeadId) -> None:
    reexec_store(home, bead).delete()


def take_net_pause(home: ConfigDir, bead: BeadId) -> NetPause | None:
    """The note a run leaves when it pauses for the network, taken once; None when there is none, it is older than
    NET_PAUSE_ADOPT_S, or the run it names is gone."""
    store = net_pause_store(home, bead)
    note = store.get()
    store.delete()
    if note is None or time.time() - note.t > NET_PAUSE_ADOPT_S:
        return None
    return note if rundocs.pause(home, note.run).get() is not None else None


def take_reexec(env: Env) -> Reexec | None:
    """The hand-over an exec'd (or fallback) run-task finds in TL_REEXEC of `env`; None on a normal start. No child is handed it
    (childenv.tool_env)."""
    return Reexec.parse(env.get(EnvVar.TL_REEXEC))


def reexec_args(argv: Sequence[str], slot: str, wt: object) -> list[str] | None:
    """run-task's own argv with its slot and worktree made explicit (`--slot any` has resolved to a slot) and --fresh/--wait
    dropped (a re-exec goes on from the checkpoint, never from the start). None when argv is not a run-task command line."""
    if not argv or argv[0] != "run-task":
        return None
    out: list[str] = []
    skip = False
    for x in argv:
        if skip:
            skip = False
        elif x in ("--slot", "--worktree"):
            skip = True
        elif x.startswith(("--slot=", "--worktree=")) or x in ("--fresh", "--wait"):
            pass
        else:
            out.append(x)
    return out + (["--slot", slot] if slot else []) + ["--worktree", str(wt)]


def exec_in_place(argv: list[str], environ: dict[str, str]) -> None:
    """Replace this process with `argv` under `environ` (childenv.exec_env: the whole environment plus the hand-over)."""
    close_held()
    os.execve(argv[0], argv, environ)


class CounterDoc(Protocol):
    def get(self) -> RunCounters | None: ...


@dataclass(frozen=True)
class Resume[T]:
    """The release handover selected for one bead, before opening its run."""

    reexec: Reexec | None
    pause: NetPause | None
    dead: T | None

    def restore(self, home: ConfigDir, run: str, restore: Callable[[CounterDoc], None],
                carry: Callable[[Path], None], note: Callable[[str], object]) -> None:
        if self.reexec:
            restore(rundocs.reexec(home, run))
        elif self.pause:
            restore(rundocs.pause(home, self.pause.run))
            carry(home.run_dir(self.pause.run))
            note(f"back from the network pause of {self.pause.run}: continuing as run {run}")


def resume[T](env: Env, home: ConfigDir, bead: BeadId, dry_run: bool, read: Callable[[], T | None],
           unfinished: Callable[[T | None], bool]) -> Resume[T]:
    """An exec wins over a network pause; foreign-bead exec notes never resume this bead."""
    taken = take_reexec(env)
    if taken and taken.bead != bead:
        taken = None
    pause = None if taken else take_net_pause(home, bead)
    checkpoint = None if dry_run or taken or pause else read()
    return Resume(taken, pause, checkpoint if unfinished(checkpoint) else None)


class ReexecBook:
    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg

    def net_pause(self, pause: NetPause) -> None:
        net_pause_store(self.cfg, BeadId(pause.bead)).write(pause)

    def note(self, note: ReexecNote) -> None:
        reexec_store(self.cfg, BeadId(note.bead)).write(note)

    def args(self, argv: Sequence[str], slot: str, wt: str) -> list[str] | None:
        return reexec_args(argv, slot, wt)

    def drop(self, bead: BeadId) -> None:
        drop_reexec(self.cfg, bead)

    def exec(self, argv: list[str], env: dict[str, str]) -> None:
        exec_in_place(argv, env)
