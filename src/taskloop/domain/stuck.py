"""The stuck rule of a running engine, from its typed log records only: no git, no process, no prose.

A run is stuck when the step it is in has been silent past runlife.silent_limit(step) (no record but Beats and no worker output),
outside a wait for a shared resource, or when its last runlife.SAME_RED check rounds ended red with one signature. Each is one
episode: it is said once, and ends with new activity (silent) or with a round that is green or red another way (same_red)."""

from dataclasses import dataclass, field

from taskloop.contracts import log as rec
from taskloop.contracts.runlife import SAME_RED, silent_limit


@dataclass
class StuckWatch:
    step_id: str = ""
    step: str = ""
    last: float = 0.0  # the newest activity: a record that is not a Beat or a Stuck, or the worker's output
    waits: set[str] = field(default_factory=set)
    reds: list[tuple[str, float]] = field(default_factory=list)  # (signature, t) of the red rounds in a row
    silent_said: bool = False
    red_said: str = ""  # the signature whose episode was said

    def feed(self, r: rec.EngineLog) -> None:
        """One record of the run's log, in order."""
        if isinstance(r, rec.Beat):
            return
        if isinstance(r, rec.Stuck):  # said already (also by the image this run moved from)
            if r.why == "silent":
                self.silent_said = True
            else:
                self.red_said = r.sig
            return
        self.saw(r.t)
        if isinstance(r, rec.StepStart):
            self.step_id, self.step = r.id, r.step
        elif isinstance(r, rec.StepEnd) and r.id == self.step_id:
            self.step_id, self.step = "", ""
        elif isinstance(r, rec.WaitStart):
            self.waits.add(r.id)
        elif isinstance(r, rec.WaitEnd):
            self.waits.discard(r.id)
        elif isinstance(r, rec.Checks):
            self.round(r)

    def saw(self, t: float) -> None:
        """Activity at `t`: a silent episode ends."""
        if t > self.last:
            self.last, self.silent_said = t, False

    def round(self, r: rec.Checks) -> None:
        sig = r.run.signature() if r.run.failed else ""
        if not sig or (self.reds and self.reds[-1][0] != sig):
            self.reds = []
        if sig:
            self.reds.append((sig, r.t))
        if sig != self.red_said:
            self.red_said = ""

    def tick(self, now: float) -> list[rec.Stuck]:
        """The Stuck records to write now (none while nothing new is stuck)."""
        out: list[rec.Stuck] = []
        if len(self.reds) >= SAME_RED and self.red_said != self.reds[-1][0]:
            sig = self.reds[-1][0]
            out.append(rec.Stuck(why="same_red", step=self.step, since=self.reds[-SAME_RED][1], sig=sig))
            self.red_said = sig
        if self.step_id and not self.waits and not self.silent_said and self.last:
            limit = silent_limit(self.step)
            if now - self.last >= limit:
                out.append(rec.Stuck(why="silent", step=self.step, since=self.last, limit_s=limit))
                self.silent_said = True
        return out
