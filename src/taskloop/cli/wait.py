"""`tl wait [--bead ID | --any] [--timeout S]`: block until a run ends or an ask opens, print one line, exit with the outcome's code.
Reads only: the typed run logs (runlife.liveness decides live, ended or crashed) and the AskStore; it polls with a sleep, no daemon."""
import argparse
import time
from argparse import Namespace
from collections.abc import Callable
from typing import Any, Final

from taskloop.app.run import requests
from taskloop.contracts import log as rec
from taskloop.contracts.enums import Outcome
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.stores import AskStore, JsonlStore

Out = Callable[[str], None]
POLL: Final = 2.0  # seconds between two looks at the files
ENDED_OK, ASK, ENDED_NOT_OK, CRASHED, NO_RUN, TIMEOUT = 0, 10, 11, 12, 13, 14
CODES: Final = f"""exit codes:
  {ENDED_OK}  the run ended landed or done
  {ASK}  an ask opened (bead and ask id on the line; tl ask show ID)
  {ENDED_NOT_OK}  the run ended parked, blocked or failed
  {CRASHED}  the run died without closing (crashed by the liveness rule)
  {NO_RUN}  no run to wait on (--bead: the bead has no run; --any: nothing is live for this repo)
  {TIMEOUT}  --timeout seconds passed, nothing happened
  2  bad arguments"""


def records(cfg: ConfigDir, run: str) -> list[rec.EngineLog]:
    path = cfg.engine_log(run)
    return [i.rec for i in JsonlStore(path, rec.decode).read_from().items] if path.exists() else []


def bead_of(run: str) -> str:
    return run.rsplit("-", 2)[0]


def repo_runs(cfg: ConfigDir, repo: str, now: float, main_checkout: Callable[[str], str]) -> list[str]:
    """The runs of this repo that are live now: a run belongs to the repo its worktree is a checkout of."""
    out: list[str] = []
    for p in sorted((cfg.root / "engine").glob("*.jsonl")):
        recs = records(cfg, p.stem)
        start = next((r for r in recs if isinstance(r, rec.RunStart)), None)
        if start and liveness(recs, now) is Liveness.LIVE and main_checkout(start.worktree) == repo:
            out.append(p.stem)
    return out


def verdict(cfg: ConfigDir, run: str, now: float) -> tuple[int, str] | None:
    """How the run stands: None while it lives, else (exit code, the line)."""
    recs = records(cfg, run)
    state = liveness(recs, now)
    if state is Liveness.LIVE:
        return None
    if state is Liveness.CRASHED:
        return CRASHED, f"crashed: {run} stopped writing without closing"
    close = next(r for r in recs if isinstance(r, rec.Close))
    why = f": {close.why}" if close.why else ""
    return (ENDED_OK if close.outcome in (Outcome.LANDED, Outcome.DONE) else ENDED_NOT_OK), f"ended {close.outcome}: {run}{why}"


def asked(asks: AskStore, beads: set[str] | None, repo: str, since: float) -> tuple[int, str] | None:
    for a in asks.live():
        if a.t >= since and (a.bead in beads if beads is not None else not a.repo or a.repo == repo):
            return ASK, f"ask: {a.bead} {a.id} [{a.kind}] {a.decision}"
    return None


def wait(a: Namespace, cfg: ConfigDir, asks: AskStore, repo: str, main_checkout: Callable[[str], str], out: Out = print,
         now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> int:
    start = now()
    bead = getattr(a, "bead", None)
    runs = [requests.newest_run(cfg, bead)] if bead else repo_runs(cfg, repo, start, main_checkout)
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
