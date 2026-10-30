"""Moving to a newer install between steps (tl-7y6.9): by exec only, no module is ever reloaded in place. The notes a run leaves for
the process that takes it over: the exec hand-over, the network pause, and the argv that goes on from the checkpoint."""
import json
import os
import time
from collections.abc import Sequence
from typing import Any

from taskloop.adapters import applog, ident
from taskloop.contracts import env as penv
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.paths import ConfigDir, RunFiles
from taskloop.contracts.run import NetPause, ReexecNote
from taskloop.contracts.stores import JsonStore
from taskloop.domain.lanes import policy as lp

RELOAD_FALLBACK_S = 120  # a run-task that dies this soon after an exec is put back on the version it came from (by the loop)
NET_PAUSE_ADOPT_S = lp.KNOBS["net_pause_max_s"]  # a run paused for the network is taken up again by the next run-task within this long


def cfg() -> ConfigDir:
    return ConfigDir(ident.config_dir())


def reexec_store(bead: str) -> JsonStore[ReexecNote]:
    return JsonStore(cfg().reexec_note(bead), ReexecNote)


def net_pause_store(bead: str) -> JsonStore[NetPause]:
    return JsonStore(cfg().net_pause(bead), NetPause)


def read_reexec(bead: str) -> ReexecNote | None:
    """The note an engine leaves just before it execs into a newer install; None when none (or not of this version)."""
    return reexec_store(bead).read()


def drop_reexec(bead: str) -> None:
    reexec_store(bead).delete()


def take_net_pause(bead: str) -> NetPause | None:
    """The note a run leaves when it pauses for the network, taken once; None when there is none, it is older than
    NET_PAUSE_ADOPT_S, or the run it names is gone."""
    store = net_pause_store(bead)
    note = store.read()
    store.delete()
    if note is None or time.time() - note.t > NET_PAUSE_ADOPT_S:
        return None
    return note if RunFiles(cfg().run_dir(note.run)).pause().is_file() else None


def take_reexec_env() -> dict[str, Any]:
    """The hand-over an exec'd (or fallback) run-task finds in TL_REEXEC: {run, bead, from, owned}; {} on a normal start."""
    raw = penv.take(EnvVar.TL_REEXEC)
    try:
        note = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return note if isinstance(note, dict) and isinstance(note.get("run"), str) else {}


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


def exec_in_place(argv: list[str]) -> None:
    applog.close_all()
    os.execv(argv[0], argv)
