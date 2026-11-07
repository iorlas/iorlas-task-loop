"""Owner park, stop and note verbs, including requests posted to a live run."""

from collections.abc import Callable
from typing import Final

from tlkernel import runlife
from tlkernel.askstore import AskStore
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.requests import OwnerNote, OwnerRequest
from tlkernel.run import RunState
from tlkernel.runlife import Liveness, liveness
from tlkernel.signalrows import SignalRows

from taskloop.app.asks.intake import Intake, receipt


def post(cfg: ConfigDir, run: str, by: str, now: float, *, repo: str, bead: str,
         park: bool = False, stop: bool = False, note: str = "") -> str:
    """Add to the observed repo/bead's live run. Identity refusal precedes every write; a request that lands
    after the run ended is dropped at its close."""
    why = runlife.command_scope(cfg, repo, bead, run, now)
    if why:
        return why
    notes = [OwnerNote(text=note.strip(), t=now, by=by)] if note.strip() else []
    SignalRows(cfg, run).post(OwnerRequest(park=park, stop=stop, notes=notes, by=by, t=now), now)
    return ""


def live(cfg: ConfigDir, run: str, now: float) -> bool:
    """Whether the recorded run state is live."""
    b = RunLocator(cfg).get(run) if run else None
    return b is not None and liveness(b.manifest) is Liveness.LIVE


def newest_run(cfg: ConfigDir, bead: str) -> str:
    """The id of the bead's newest run that has an engine log ("" when it has none)."""
    return next((b.run for b in reversed(RunLocator(cfg).of_bead(bead)) if b.log.exists()), "")


class OwnerVerbs:
    """park, stop and note as the owner says them (`tl park|note`, the dashboard's Ports): the hold and the receipt through Intake, the
    run's part through its request file. -> "" or why nothing was done; `said` is what the owner reads on success."""

    def __init__(self, intake: Intake, cfg: ConfigDir, now: float, repo: str) -> None:
        self.intake, self.cfg, self.now, self.repo = intake, cfg, now, repo

    def park(self, bead: BeadId, run: str) -> tuple[str, str]:
        """The loop keeps off the bead (a hold until released); a live run ends at its next step boundary, branch kept."""
        if run:
            why = post(self.cfg, run, self.intake.by, self.now, repo=self.repo, bead=bead, park=True)
            if why:
                return why, ""
        self.intake.hold(bead)
        if not run:
            return "", "Parked: no run is going, and the loop will not take it until the hold is released."
        return "", "Parks at the next step; the branch is kept."

    def stop(self, bead: BeadId, run: str) -> tuple[str, str]:
        """The live run ends now (its stop flag); the branch is kept and the hold keeps the loop from starting it again."""
        why = post(self.cfg, run, self.intake.by, self.now, repo=self.repo, bead=bead, stop=True)
        if why:
            return why, ""
        self.intake.hold(bead)
        return "", "Stopping; the branch is kept."

    def note(self, bead: BeadId, run: str, text: str) -> tuple[str, str]:
        """For the next stage's worker of the live run; with no run going, a hint the next run reads. A receipt comment either way."""
        if not text.strip():
            return "write a note first", ""
        if run:
            why = post(self.cfg, run, self.intake.by, self.now, repo=self.repo, bead=bead, note=text)
            if why:
                return why, ""
        if not run:
            self.intake.hint(bead, text)
            return "", "No run is going: saved as a hint the next run reads."
        self.intake.note(bead, receipt("note", text.strip()))
        return "", "Sent: the next stage reads it."


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
    return [b.run for b in RunLocator(cfg).of_repo(repo) if runlife.shown(b.manifest, now) in (Liveness.LIVE, Liveness.SUSPECT)]


def verdict(cfg: ConfigDir, run: str, now: float) -> tuple[int, str] | None:
    """How the run stands, from its recorded state: None while it lives, else (exit code, the line)."""
    b = RunLocator(cfg).get(run)
    if b is None:
        return NO_RUN, f"no run: {run} has no manifest"
    m = b.manifest
    why = f": {m.reason}" if m.reason else ""
    life = runlife.shown(m, now)
    if m.state.live:
        if life is Liveness.LOST:
            return CRASHED, f"lost: {run}: {runlife.lost_reason(m, now)}"
        return None
    if m.state is RunState.LOST:
        return CRASHED, f"lost: {run}{why}"
    return (ENDED_OK if m.state is RunState.DONE else ENDED_NOT_OK), f"ended {m.state}: {run}{why}"


def asked(asks: AskStore, beads: set[str] | None, repo: str, since: float) -> tuple[int, str] | None:
    for a in asks.live():
        if a.t >= since and (a.bead in beads if beads is not None else not a.repo or a.repo == repo):
            return ASK, f"ask: {a.bead} {a.id} [{a.kind}] {a.decision}"
    return None


def wait(cfg: ConfigDir, asks: AskStore, repo: str, bead: str | None, limit: float | None,
         now: Callable[[], float], sleep: Callable[[float], None]) -> tuple[int, str]:
    """Poll run state and new asks, returning the exit code and the line for the owner."""
    start = now()
    runs = [newest_run(cfg, bead)] if bead else repo_runs(cfg, repo, start)
    runs = [r for r in runs if r]
    if not runs:
        return NO_RUN, f"no run: {bead} has no run" if bead else f"no run: nothing is live for {repo}"
    while True:
        t = now()
        if bead:  # the bead's run is the thing waited on; an ask it opened ends the wait too
            got = verdict(cfg, runs[0], t) or asked(asks, {bead}, repo, start)
        else:  # any: the first of the runs live at the start to end, or any ask of the repo
            got = next((v for v in (verdict(cfg, r, t) for r in runs) if v), None) or asked(asks, None, repo, start)
        if got:
            return got
        if limit is not None and t - start >= limit:
            return TIMEOUT, f"timeout: nothing ended or asked in {limit:g} s"
        sleep(min(POLL, limit - (t - start)) if limit is not None else POLL)
