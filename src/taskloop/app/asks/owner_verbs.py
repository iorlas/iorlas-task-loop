"""Owner park, stop and note verbs, including requests posted to a live run."""

from taskloop.app.asks.intake import Intake, receipt
from taskloop.contracts import runlife
from taskloop.contracts.ids import BeadId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.requests import OwnerNote, OwnerRequest
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.signalrows import SignalRows


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
    """Whether a run is live after reconciling engines whose processes died."""
    runlife.reconcile(cfg, now)
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
