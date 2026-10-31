"""The bead's last state: closed (landed or done), left open (a machine fault, a pause, the owner's hold) or blocked on the owner."""
import time
from typing import Protocol, assert_never

from taskloop.adapters import beadtools
from taskloop.app.asks import parks
from taskloop.app.track import verbs as track
from taskloop.contracts import fence
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Infra, Kind, Owner, Task
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BeadPatch, Beads
from taskloop.domain import outcome as oc
from taskloop.domain.land.matchers import without_prefix


class SettleConfig(Protocol):
    @property
    def base(self) -> str: ...


class SettleHost(Protocol):
    """What settling the bead reads of the engine: the bead, its claim and bd, the plan's summary, the base, the disposition."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def store(self) -> Beads: ...
    @property
    def who(self) -> Identity: ...
    @property
    def home(self) -> ConfigDir: ...
    @property
    def cfg(self) -> SettleConfig: ...
    @property
    def run_id(self) -> str: ...
    @property
    def plan_summary(self) -> str: ...
    @property
    def disp(self) -> oc.Disposition | None: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...


class Settle:
    def __init__(self, host: SettleHost) -> None:
        self.e = host

    def run(self, done: oc.RunOutcome, stats: str) -> None:
        e = self.e
        summary = e.plan_summary[:300]
        match done.fault:
            case None if done.kind is Kind.LANDED:
                base = e.cfg.base.split("/")[-1]
                rc = track.close_as(e.who, e.claim, f"merged {done.sha[:12]} to {base}: {summary or 'the task stages passed'}; {stats}",
                    e.store)
            case None:
                rc = track.close_as(e.who, e.claim, "done with nothing to land: " + (summary or stats), e.store)
            case Infra() | Owner():  # a machine fault, a pause or the owner's hold: the bead stays open, unassigned
                rc = self.leave_open(done.kind, done.detail)
            case Task():
                q = ("\n\nQuestion: " + done.spec.decision) if done.spec else ""
                rc = track.block_as(e.who, e.claim, done.detail + q, e.store, e.comment)
            case fault:
                assert_never(fault)
        if bead := beadtools.peek(e.store, e.bead):  # the text this run ended on: the next run of it is judged against it (tl-7y6.7.3)
            parks.ended(e.home, bead, done.kind, e.run_id, time.time())
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            e.warn(f"bd refused to {'close' if done.finished else 'block'} {e.bead} (exit {rc}): close it by hand")

    def leave_open(self, kind: Kind, why: str) -> int:
        e = self.e
        fault = kind.name.startswith("FAULT_")
        if not fault:
            e.warn(why)
        if why_not := fence.stale(e.store, e.claim):  # a run whose bead or slot was taken again lets go of nothing
            e.warn(f"fenced: {e.bead} left as it is: {why_not}")
            return 1
        patch = BeadPatch(status="open", assignee="", if_assignee=fence.guard(e.claim))  # (tl-kwo: it lets go; only its own claim)
        rc = 0 if beadtools.attempt(e.store.update, e.bead, patch) else 1
        if oc.POLICY[kind].label:
            beadtools.attempt(e.store.add_label, e.bead, oc.POLICY[kind].label)
        if e.disp and e.disp.comment:  # a comment, never Notes (tl-7y6.6.2); one per (bead, kind, fingerprint) per hour
            e.comment("Engine {}: {}".format("failed" if fault else "paused", without_prefix(why)[:400]))
        return rc
