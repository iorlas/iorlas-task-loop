"""The owner's requests to a live run (contracts/requests.py): `post` merges one into the run's request file, `take` hands the whole
file to the run once. Both hold the file's lock (the kernel drops it with the process), so a request written while the run
takes the file is never lost or taken twice. The run acts on them (OwnerRequests): stop at its Beat or next step boundary through its
stop flag, park and the notes at its next step boundary."""

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json

from taskloop.adapters import locks
from taskloop.app.asks.intake import Intake, receipt
from taskloop.contracts import log as rec
from taskloop.contracts import wire
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.requests import OwnerNote, OwnerRequest
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.stores import JsonlStore
from taskloop.domain import outcome as oc

PARKED_WHY = "parked: by the owner (the branch and the checkpoint are kept; release the hold to go on)"
STOPPED_WHY = "failed: stopped by the owner"
NOTE_HEAD = "\n\n## The owner's note for this stage\n"


@contextlib.contextmanager
def locked(cfg: ConfigDir, run: str) -> Iterator[Path]:
    """The run's request file, under its lock (the one lock primitive, adapters/locks.py)."""
    lock = cfg.run_request_lock(run)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with locks.hold_path(lock, "owner-request", timeout=30):
        yield cfg.run_request(run)


def read(path: Path) -> OwnerRequest | None:
    try:
        return wire.load(OwnerRequest, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):  # none, torn, or a foreign version: no request
        return None


def live(cfg: ConfigDir, run: str, now: float) -> bool:
    """Whether the run still writes (runlife.liveness over its typed log)."""
    path = cfg.engine_log(run)
    if not run or not path.exists():
        return False
    return liveness([i.rec for i in JsonlStore(path, rec.decode).read_from().items], now) is Liveness.LIVE


def post(cfg: ConfigDir, run: str, by: str, now: float, *, park: bool = False, stop: bool = False, note: str = "") -> str:
    """Merge a request into the live run's file. -> "" or why it was refused (the run is not live)."""
    if not live(cfg, run, now):
        return "no run of this bead is going"
    with locked(cfg, run) as path:
        old = read(path) or OwnerRequest()
        notes = old.notes + ([OwnerNote(text=note.strip(), t=now, by=by)] if note.strip() else [])
        atomic_write_json(path, wire.dump(OwnerRequest(park=old.park or park, stop=old.stop or stop, notes=notes, by=by, t=now)),
                          indent=1, fsync=False)
    return ""


def take(cfg: ConfigDir, run: str) -> OwnerRequest | None:
    """The run's pending request, removed: each is acted on once."""
    if not cfg.run_request(run).exists():
        return None
    with locked(cfg, run) as path:
        got = read(path)
        path.unlink(missing_ok=True)
    return got


def peek(cfg: ConfigDir, run: str) -> OwnerRequest | None:
    return read(cfg.run_request(run))


class OwnerRequests:
    """The run's side: what it does with the owner's requests."""

    def __init__(self, host: Any) -> None:
        self.e = host
        self.notes: list[OwnerNote] = []  # taken, for the next worker call's prompt
        self.stopped = False  # the owner's stop set the stop flag: the close names the owner, not a SIGTERM
        self.closing = False  # the close-out began: nothing is taken any more (a step of the close-out is no safe point to end at)

    @property
    def cfg(self) -> ConfigDir:
        return ConfigDir(self.e.run_dir.parent.parent)

    @property
    def run(self) -> str:
        return self.e.run_dir.name

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
            raise self.e.Blocked(PARKED_WHY, kind=oc.Kind.OWNER_PARK)

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
        with contextlib.suppress(OSError):
            take(self.cfg, self.run)


def newest_run(cfg: ConfigDir, bead: str) -> str:
    """The stem of the bead's newest engine log ("" when it has none): <bead>-<YYYYMMDD-HHMMSS> sorts by time."""
    pattern = cfg.engine_log(f"{bead}-*")
    stamps = [p.stem for p in pattern.parent.glob(pattern.name) if is_stamp(p.stem[len(bead) + 1:])]
    return max(stamps, default="")


def is_stamp(text: str) -> bool:
    day, _, clock = text.partition("-")
    return len(day) == 8 and len(clock) == 6 and day.isdigit() and clock.isdigit()


class OwnerVerbs:
    """park, stop and note as the owner says them (`tl park|note`, the dashboard's Ports): the hold and the receipt through Intake, the
    run's part through its request file. -> "" or why nothing was done; `said` is what the owner reads on success."""

    def __init__(self, intake: Intake, cfg: ConfigDir, now: float) -> None:
        self.intake, self.cfg, self.now = intake, cfg, now

    def park(self, bead: str, run: str) -> tuple[str, str]:
        """The loop keeps off the bead (a hold until released); a live run ends at its next step boundary, branch kept."""
        self.intake.hold(bead)
        if post(self.cfg, run, self.intake.by, self.now, park=True):
            return "", "Parked: no run is going, and the loop will not take it until the hold is released."
        return "", "Parks at the next step; the branch is kept."

    def stop(self, bead: str, run: str) -> tuple[str, str]:
        """The live run ends now (its stop flag); the branch is kept and the hold keeps the loop from starting it again."""
        why = post(self.cfg, run, self.intake.by, self.now, stop=True)
        if why:
            return why, ""
        self.intake.hold(bead)
        return "", "Stopping; the branch is kept."

    def note(self, bead: str, run: str, text: str) -> tuple[str, str]:
        """For the next stage's worker of the live run; with no run going, a hint the next run reads. A receipt comment either way."""
        if not text.strip():
            return "write a note first", ""
        if post(self.cfg, run, self.intake.by, self.now, note=text):
            self.intake.hint(bead, text)
            return "", "No run is going: saved as a hint the next run reads."
        self.intake.note(bead, receipt("note", text.strip()))
        return "", "Sent: the next stage reads it."
