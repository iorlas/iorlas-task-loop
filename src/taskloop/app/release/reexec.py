"""Moving to a newer install between steps (tl-7y6.9): by exec only, no module is ever reloaded in place. The notes a run leaves for
the process that takes it over: the exec hand-over, the network pause, and the argv that goes on from the checkpoint."""
import os
import time
from collections.abc import Sequence

from jsonl_log import close_held

from taskloop.contracts import rundocs
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import NetPause, Reexec, ReexecNote
from taskloop.contracts.waitrows import NET_PAUSE, REEXEC, WaitDoc
from taskloop.domain.lanes import policy as lp

NET_PAUSE_ADOPT_S = lp.KNOBS["net_pause_max_s"]  # a run paused for the network is taken up again by the next run-task within this long


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
