"""The close: the one step every run ends with. The branch is saved (a wip commit, the checkpoint marked closed), the outcome is decided by
POLICY, the run is written to the log and the trace, follow-ups are filed, and the bead is closed, blocked or left open."""
import contextlib
import signal
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import assert_never

from taskloop.adapters import beadtools, ident
from taskloop.adapters import storm as storm_file
from taskloop.app.asks import raiser
from taskloop.app.land.followups import file_follow_ups
from taskloop.app.run import outcomes
from taskloop.app.run import trace as runtrace
from taskloop.app.run.closer_host import CloserHost
from taskloop.app.run.console import say
from taskloop.app.run.interpret import interpret
from taskloop.app.run.state import CheckpointLedger
from taskloop.app.track import verbs as track
from taskloop.contracts import fence
from taskloop.contracts import log as rec
from taskloop.contracts.answers import VERDICTS
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ports import BeadPatch
from taskloop.domain import effects, storm
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.land.matchers import without_prefix
from taskloop.domain.review import followups as fu

DONE = (Outcome.LANDED, Outcome.DONE)


class Closer:
    """The close of a run: the outcome's policy, the log and trace, the bead's last state."""

    def __init__(self, host: CloserHost) -> None:
        self.e = host

    def close(self, ended: oc.RunOutcome) -> None:
        e = self.e
        e.halt.clear()  # the close-out runs commands: the stop flag has done its work
        old = None
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            old = signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        try:
            self.run(ended)
        finally:  # what the process starts after this (a notify command, the next test) must stay stoppable
            if old is not None:
                signal.signal(signal.SIGTERM, old)

    def repo_id(self) -> str:
        return self.e.git("remote", "get-url", "origin") or str(self.e.wt)

    def decide(self, o: oc.RunOutcome) -> oc.Kind:
        """The close's Kind after POLICY: a fault seen too often on one bead becomes one ask; the trace fields, the fingerprint and
        the storm check (never for a pause or an ask) are set here."""
        e = self.e
        e.disp = None
        kind, why = o.kind, o.detail
        now = e.clock.now()
        e.fp = o.fingerprint
        history: Sequence[Mapping[str, object]] = ()
        with contextlib.suppress(OSError):
            history = storm_file.recent_closes(ident.config_dir() / "traces.jsonl", self.repo_id(), now)
        e.disp = oc.apply(o, e.bead, history, now)
        e.kind = e.disp.kind
        if e.disp.escalated:
            e.warn(f"the same fault {oc.KNOBS['fault_retries']} times on this bead: asking the owner once")
        self.storm(history, kind, o, why)
        return e.kind

    def storm(self, history: Sequence[Mapping[str, object]], kind: oc.Kind, o: oc.RunOutcome, why: str) -> None:
        e = self.e
        trip = storm.storm_trip(history, e.bead, kind, o.fingerprint, e.clock.now())
        if trip and not e.dry:
            path = storm_file.storm_path(ident.config_dir(), self.repo_id())
            if storm_file.write_storm(path, trip.fingerprint, trip.beads, trip.t, e.clock.now(), oc.KNOBS["storm_window_s"], why):
                e.storm = storm.banner(trip)
                e.warn(e.storm)
                say(e.storm)

    def run(self, ended: oc.RunOutcome) -> None:
        e = self.e
        why = ended.detail or ("stopped before a reason was recorded" if ended.word is Outcome.FAILED else "")
        bad = raiser.problems(ended.spec) if ended.spec else []
        if bad:  # an ask that is no ask an owner can answer is the engine's own fault; no prose question takes its place
            first = why.splitlines()[0][:200] if why else ""
            why = f"failed: ask_lint: {'; '.join(bad)[:300]} ({first})"
            ended = oc.make(oc.Kind.FAULT_ENGINE, why)
        kind = self.decide(oc.make(ended.kind, why, spec=ended.spec))
        spec = ended.spec
        if e.disp and e.disp.escalated and spec is None:
            spec = askspecs.repeated_fault(oc.KNOBS["fault_retries"], why.splitlines()[0][:200])
        done = oc.make(kind, why, sha=ended.sha, spec=spec if kind in oc.ASKS else None)  # the final outcome: its word is the trace's
        counts = "; ".join(f"{k}={v}" for k, v in e.stats.items())
        stats = f"cost=${e.cost:.2f}; minutes={int((time.time() - e.t0) / 60)}; {counts}"
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        slot_gen = e.claim.slot_gen
        plan = effects.plan_close(done, dry=e.dry, branch=branch, slot_gen=slot_gen)
        new = fu.batch(e.bead, e.leftovers, e.filed).file  # one per typed key, at most the cap
        lost: list[dict[str, str]] = []
        interpret(e.bead, e.log_path.stem, plan, CheckpointLedger(e.checkpoints),
                  lambda eff: self.apply(eff, done, stats, new, lost))

    def apply(self, eff: effects.Effect, done: oc.RunOutcome, stats: str, new: Sequence[Mapping[str, str]],
              lost: list[dict[str, str]]) -> None:
        """One effect of the close plan, done. The match is closed: a new effect is one more case here."""
        e = self.e
        outcome, why = done.word, done.detail
        match eff:
            case effects.SaveBranch():
                self.save_branch(outcome, why)
            case effects.RecordRun():
                self.record(done, stats)
            case effects.NoteDry():
                e.log.note(f"dry run: bead left as it was. {stats}")
            case effects.NoteWait():  # asked already: the bead stays as the ask left it
                e.log.note(why)
            case effects.RaiseAsk():
                e.asked = bool(done.spec and outcome not in DONE and e.ask_flow.raise_ask(done.spec, why, done.kind))
            case effects.FileNotes():
                lost[:] = self.follow_ups(outcome)
            case effects.Reflect():
                self.reflect_comment(outcome, why, new, lost, stats)
            case effects.CloseBead() | effects.BlockBead() | effects.LeaveBead():
                self.settle(done, stats)
            case effects.ReleaseSlot():
                self.release_slot(eff, outcome)
            case _:
                assert_never(eff)

    def release_slot(self, eff: effects.ReleaseSlot, outcome: Outcome) -> None:
        """Last: the trace and the comments read the branch. A slot whose lease moved on (another generation) is not this run's to touch."""
        e = self.e
        with contextlib.suppress(Exception):
            if e.claim.slot_bead and fence.stale(e.store, e.claim):
                return
            e.tree.leave_slot(outcome, eff.branch)

    def save_branch(self, outcome: Outcome, why: str) -> None:
        """A run stopped mid-conflict-fix goes back to its branch; an unfinished branch keeps its work as a wip commit and a
        closed checkpoint."""
        e = self.e
        gd = Path(e.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
            e.sh(["git", "rebase", "--abort"], pin=True)
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        if outcome not in DONE and branch and branch == (e.branch or None):
            if e.git("status", "--porcelain"):
                e.tree.wip(outcome)  # the next run continues this branch
            e.checkpoints.close(why)

    def record(self, done: oc.RunOutcome, stats: str) -> None:
        """The run's log and trace: the close node, the reflection, the owner's question."""
        e = self.e
        outcome, why, sha, spec, kind = done.word, done.detail, done.sha, done.spec, done.kind
        e.records.log_run()
        last = e.steps.cur or e.steps.last
        if last and (e.steps.moved_from != last.n or e.steps.moved_to not in ("ask", "pause", "close")):
            to, cause = outcomes.close_move(kind)  # no move out of the run was logged from the last node: the close is it
            e.steps.move(to, cause, why.splitlines()[0][:200] if why else outcome)
        e.steps.end(outcomes.node_outcome(outcome, kind))
        e.steps.begin("close", f"close: {outcome}")
        code = runtrace.why_code(kind.value, outcome)
        e.log.emit(rec.Close(outcome=Outcome(outcome), why_code=code, sha=sha or "", why=why[:500]))
        e.steps.outcome(outcome, why.splitlines()[0][:200] if why else "")
        e.steps.end()
        e.reflection = e.reflector.reflect_run(outcome, why)  # after the close node: the outcome is decided and nothing here changes it
        e.records.file_trace(outcome, why, sha)
        e.detail([stats] + ([why[:400]] if why else []) + (["question: " + spec.decision[:400]] if spec else []))
        if outcome is Outcome.FAILED:
            e.warn(f"task failed: {why.splitlines()[0][:200]}")

    def follow_ups(self, outcome: Outcome) -> list[dict[str, str]]:
        """Landed work leaves its notes: the ask closed, the unverified items and the unchecked look items said, evidence kept, and each
        follow-up filed as a bead (what bd refuses is kept in the checkpoint, none lost)."""
        e = self.e
        if outcome in DONE:
            old = e.stores.asks.get(e.bead)
            if old:
                e.stores.asks.close(e.bead, old.id, "the run landed", time.time())
            if e.unverified:
                e.comment("Land (engine): " + e.owner_look.unverified_text())
            look = [u for u in e.unchecked if u["kind"] == "other" and not e.judge.is_look(u)]
            if look:
                beadtools.attempt(e.store.add_label, e.bead, "needs-owner-check")
                e.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = e.pictures.keep_evidence()
        if shots:
            e.comment("Evidence (engine): " + ", ".join(str(p) for p in shots))
        lost = file_follow_ups(e)
        if outcome is Outcome.LANDED:
            e.owner_look.file_owner_look()
        return lost

    def reflect_comment(self, outcome: Outcome, why: str, new: Sequence[Mapping[str, str]], lost: Sequence[object], stats: str) -> None:
        e = self.e
        verified = ""
        if e.verified:
            verified = "; self-verified=" + ", ".join("{} {}".format(sum(x["verdict"] == k for x in e.verified), k) for k in VERDICTS)
        unfiled = f" unfiled={len(lost)};" if lost else ""
        text = outcomes.reflection_text(e.reflection)
        e.comment(f"Reflect (engine): outcome={outcome};{text} filed={len(new) - len(lost)};{unfiled} {stats}"
                  f"{verified}{('; why=' + why) if why else ''}; trace={e.log_path.stem} (tl trace {e.bead})")

    def settle(self, done: oc.RunOutcome, stats: str) -> None:
        """The bead's status: closed (landed or done), left open (a machine fault, a pause, the owner's hold) or blocked on the owner."""
        e = self.e
        summary = e.plan_summary[:300]
        match done.fault:
            case None if done.kind is oc.Kind.LANDED:
                base = e.cfg.base.split("/")[-1]
                rc = track.close_as(e.claim, f"merged {done.sha[:12]} to {base}: {summary or 'the task stages passed'}; {stats}", e.store)
            case None:
                rc = track.close_as(e.claim, "done with nothing to land: " + (summary or stats), e.store)
            case oc.Infra() | oc.Owner():  # a machine fault, a pause or the owner's hold: the bead stays open, unassigned
                rc = self.leave_open(done.kind, done.detail)
            case oc.Task():
                q = ("\n\nQuestion: " + done.spec.decision) if done.spec else ""
                rc = track.block_as(e.claim, done.detail + q, e.store, e.comment)
            case fault:
                assert_never(fault)
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            e.warn(f"bd refused to {'close' if done.finished else 'block'} {e.bead} (exit {rc}): close it by hand")

    def leave_open(self, kind: oc.Kind, why: str) -> int:
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
