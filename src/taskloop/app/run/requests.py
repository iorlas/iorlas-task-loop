"""The owner's requests to a live run (contracts/requests.py): `post` adds one as a `signal` row, `take` hands the run's untaken rows
to it once, merged (contracts/signalrows.py), so a request written while the run takes is never lost or taken twice. The run acts on
them (OwnerRequests): stop at its Beat or next step boundary through its stop flag, park and the notes at its next step boundary."""

import contextlib
import time
from typing import Any

from taskloop.app.asks.intake import Intake, receipt
from taskloop.contracts import factorydb, runlife
from taskloop.contracts import log as rec
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.requests import OwnerNote, OwnerRequest
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.signalrows import SignalRows

PARKED_WHY = "parked: by the owner (the branch and the checkpoint are kept; release the hold to go on)"
STOPPED_WHY = "failed: stopped by the owner"
NOTE_HEAD = "\n\n## The owner's note for this stage\n"


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


def take(cfg: ConfigDir, run: str, now: float = 0.0) -> OwnerRequest | None:
    """The run's pending request, taken: each is acted on once."""
    return SignalRows(cfg, run).take(now or time.time())


def peek(cfg: ConfigDir, run: str) -> OwnerRequest | None:
    return SignalRows(cfg, run).peek()


class OwnerRequests:
    """The run's side: what it does with the owner's requests."""

    def __init__(self, host: Any) -> None:
        self.e = host
        self.notes: list[OwnerNote] = []  # taken, for the next worker call's prompt
        self.stopped = False  # the owner's stop set the stop flag: the close names the owner, not a SIGTERM
        self.closing = False  # the close-out began: nothing is taken any more (a step of the close-out is no safe point to end at)

    @property
    def cfg(self) -> ConfigDir:
        return self.e.home

    @property
    def run(self) -> str:
        return self.e.run_id

    def at_beat(self) -> None:
        """A stop is acted on now: the run's stop flag, as a SIGTERM sets it. The file stays for the step boundary to take."""
        got = None if self.closing else peek(self.cfg, self.run)
        if got is not None and got.stop and not self.stopped:
            self.stopped = True
            self.e.halt.set()

    def at_step(self, step: str) -> None:
        """A step boundary (a safe point): take the file; a stop or a park ends the run here, notes wait for the next worker call."""
        got = None if self.closing else take(self.cfg, self.run)
        if got is None:
            return
        for n in got.notes:
            self.e.log.emit(rec.Said(step=self.e.step_id(), who="owner", text=n.text))
        self.notes += got.notes
        if got.stop:
            self.stopped = True
            self.e.halt.set()
            self.e.halt_point()
        if got.park:
            self.e.steps.move("pause", "owner_park", f"the owner parked it before {step}")
            raise self.e.Blocked(PARKED_WHY, kind=Kind.OWNER_PARK)

    def prompt_tail(self) -> str:
        """The notes taken since the last worker call, as the prompt's last section; then they are given."""
        if not self.notes:
            return ""
        text = NOTE_HEAD + "\n".join(f"- {n.text}" for n in self.notes) + "\n"
        self.notes = []
        return text

    def drop(self) -> None:
        """At the close: a request the run did not take is for a run that has ended; it is dropped, never acted on later."""
        self.closing = True
        with contextlib.suppress(OSError, factorydb.DatabaseError):
            take(self.cfg, self.run)


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
