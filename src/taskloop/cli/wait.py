"""`tl wait [--bead ID | --any] [--timeout S]`: block until a run ends or an ask opens, print one line, exit with the outcome's code.
Reads a run's recorded state (its manifest: live, done, failed, parked, stopped or lost) and the AskStore; it polls with a sleep, no daemon.
Each poll runs the one reconciler first, so a killed engine reads lost here and not never."""
import argparse
import time
from argparse import Namespace
from collections.abc import Callable
from typing import Any, Final

from taskloop.app.run import requests
from taskloop.contracts import runlife
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.stores import AskStore

Out = Callable[[str], None]
POLL: Final = 2.0  # seconds between two looks at the files
ENDED_OK, ASK, ENDED_NOT_OK, CRASHED, NO_RUN, TIMEOUT = 0, 10, 11, 12, 13, 14
CODES: Final = f"""exit codes:
  {ENDED_OK}  the run ended landed or done
  {ASK}  an ask opened (bead and ask id on the line; tl ask show ID)
  {ENDED_NOT_OK}  the run ended parked, blocked or failed
  {CRASHED}  the run is lost: its process died and recorded no end
  {NO_RUN}  no run to wait on (--bead: the bead has no run; --any: nothing is live for this repo)
  {TIMEOUT}  --timeout seconds passed, nothing happened
  2  bad arguments"""


def repo_runs(cfg: ConfigDir, repo: str, now: float) -> list[str]:
    """The runs of this repo that are live now: a run belongs to the repo its manifest names."""
    runlife.reconcile(cfg, now)
    return [b.run for b in RunLocator(cfg).of_repo(repo) if liveness(b.manifest) is Liveness.LIVE]


def verdict(cfg: ConfigDir, run: str, now: float) -> tuple[int, str] | None:
    """How the run stands, from its recorded state: None while it lives, else (exit code, the line)."""
    runlife.reconcile(cfg, now)
    b = RunLocator(cfg).get(run)
    if b is None:
        return NO_RUN, f"no run: {run} has no manifest"
    m = b.manifest
    why = f": {m.reason}" if m.reason else ""
    if m.state.live:
        return None
    if m.state is RunState.LOST:
        return CRASHED, f"lost: {run}{why}"
    return (ENDED_OK if m.state is RunState.DONE else ENDED_NOT_OK), f"ended {m.state}: {run}{why}"


def asked(asks: AskStore, beads: set[str] | None, repo: str, since: float) -> tuple[int, str] | None:
    for a in asks.live():
        if a.t >= since and (a.bead in beads if beads is not None else not a.repo or a.repo == repo):
            return ASK, f"ask: {a.bead} {a.id} [{a.kind}] {a.decision}"
    return None


def wait(a: Namespace, cfg: ConfigDir, asks: AskStore, repo: str, out: Out = print,
         now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> int:
    start = now()
    bead = getattr(a, "bead", None)
    runs = [requests.newest_run(cfg, bead)] if bead else repo_runs(cfg, repo, start)
    runs = [r for r in runs if r]
    if not runs:
        out(f"no run: {bead} has no run" if bead else f"no run: nothing is live for {repo}")
        return NO_RUN
    limit = getattr(a, "timeout", None)
    while True:
        t = now()
        if bead:  # the bead's run is the thing waited on; an ask it opened ends the wait too
            got = verdict(cfg, runs[0], t) or asked(asks, {bead}, repo, start)
        else:  # any: the first of the runs live at the start to end, or any ask of the repo
            got = next((v for v in (verdict(cfg, r, t) for r in runs) if v), None) or asked(asks, None, repo, start)
        if got:
            out(got[1])
            return got[0]
        if limit is not None and t - start >= limit:
            out(f"timeout: nothing ended or asked in {limit:g} s")
            return TIMEOUT
        sleep(min(POLL, limit - (t - start)) if limit is not None else POLL)


def add_parser(sp: Any) -> None:
    p = sp.add_parser("wait", help="block until a run ends or an ask opens; one line, the exit code says which",
                      epilog=CODES, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bead", metavar="ID", help="wait for the newest run of this bead (or an ask on it)")
    g.add_argument("--any", action="store_true", help="wait for any run of this repo's loop that is live now (or any ask of the repo)")
    p.add_argument("--timeout", type=float, metavar="S", help=f"give up after S seconds (exit {TIMEOUT})")
    p.add_argument("--repo")
