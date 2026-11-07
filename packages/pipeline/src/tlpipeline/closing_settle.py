"""The bead's last state: closed (landed or done), left open (a machine fault, a pause, the owner's hold) or blocked on the owner."""
import time
from typing import Protocol, assert_never

from tlkernel import fence
from tlkernel import runoutcome as oc
from tlkernel.beadsport import BeadPatch, Beads
from tlkernel.ids import BeadId
from tlkernel.kinds import Infra, Kind, Owner, Task
from tlkernel.landmatchers import without_prefix
from tlpipeline.adapter_ports import Attempt, PeekBead
from tlpipeline.ports import BeadClosing, ParkBook


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
    def __init__(self, context: SettleHost, beads: BeadClosing, parks: ParkBook, peek: PeekBead, attempt: Attempt) -> None:
        self.host = context
        self.peek, self.attempt = peek, attempt
        self.beads, self.parks = beads, parks

    def run(self, done: oc.RunOutcome, stats: str) -> None:
        host = self.host
        summary = host.plan_summary[:300]
        match done.fault:
            case None if done.kind is Kind.LANDED:
                base = host.cfg.base.split("/")[-1]
                rc = self.beads.close(host.claim, f"merged {done.sha[:12]} to {base}: {summary or 'the task stages passed'}; {stats}")
            case None:
                rc = self.beads.close(host.claim, "done with nothing to land: " + (summary or stats))
            case Infra() | Owner():  # a machine fault, a pause or the owner's hold: the bead stays open, unassigned
                rc = self.leave_open(done.kind, done.detail)
            case Task():
                q = ("\n\nQuestion: " + done.spec.decision) if done.spec else ""
                rc = self.beads.block(host.claim, done.detail + q, host.comment)
            case fault:
                assert_never(fault)
        # The next run is judged against the text this run ended on (tl-7y6.7.3).
        if bead := self.peek(host.store, host.bead):
            self.parks.ended(bead, done.kind, host.run_id, time.time())
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            host.warn(f"bd refused to {'close' if done.finished else 'block'} {host.bead} (exit {rc}): close it by hand")

    def leave_open(self, kind: Kind, why: str) -> int:
        host = self.host
        fault = kind.name.startswith("FAULT_")
        if not fault:
            host.warn(why)
        if why_not := fence.stale(host.store, host.claim):  # a run whose bead or slot was taken again lets go of nothing
            host.warn(f"fenced: {host.bead} left as it is: {why_not}")
            return 1
        patch = BeadPatch(status="open", assignee="", if_assignee=fence.guard(host.claim))  # (tl-kwo: it lets go; only its own claim)
        rc = 0 if self.attempt(host.store.update, host.bead, patch) else 1
        if oc.POLICY[kind].label:
            self.attempt(host.store.add_label, host.bead, oc.POLICY[kind].label)
        if host.disp and host.disp.comment:  # a comment, never Notes (tl-7y6.6.2); one per (bead, kind, fingerprint) per hour
            host.comment("Engine {}: {}".format("failed" if fault else "paused", without_prefix(why)[:400]))
        return rc
