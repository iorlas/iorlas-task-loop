"""The close: the one step every run ends with. The branch is saved (a wip commit, the checkpoint marked closed), the outcome is decided by
POLICY, the run is written to the log and the trace, follow-ups are filed, and the bead is closed, blocked or left open."""
import contextlib
import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from taskloop.app.asks import raiser
from taskloop.app.land.followups import file_follow_ups
from taskloop.contracts import log as rec
from taskloop.contracts.answers import VERDICTS
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ports import BeadPatch
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.land.matchers import without_prefix
from taskloop.domain.review import followups as fu

DONE = ("landed", "done")


class Closer:
    """`ops` carries the engine-side helpers the close needs: oc (outcome), loop_health, tl, say, outcome_for, node_outcome, close_move,
    reflection_text, why_code, Args."""

    def __init__(self, host: Any, ops: SimpleNamespace) -> None:
        self.e, self.o = host, ops

    def close(self, outcome: str, why: str, sha: str, spec: Any, kind: Any = None) -> None:
        e = self.e
        e.halt.clear()  # the close-out runs commands: the stop flag has done its work
        old = None
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            old = signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        try:
            self.run(outcome, why, sha, spec, kind)
            if not e.dry:
                with contextlib.suppress(Exception):  # last: the trace and the comments above read the branch
                    e.tree.leave_slot(outcome, branch)
        finally:  # what the process starts after this (a notify command, the next test) must stay stoppable
            if old is not None:
                signal.signal(signal.SIGTERM, old)

    def repo_id(self) -> str:
        return self.e.git("remote", "get-url", "origin") or str(self.e.wt)

    def decide(self, outcome: str, why: str, kind: Any) -> Any:
        """The close's Kind after POLICY: a fault seen too often on one bead becomes one ask; the trace fields, the fingerprint and
        the storm check (never for a pause or an ask) are set here. kind None: the verify-gaps ask."""
        e, oc = self.e, self.o.oc
        e.disp = None
        if kind is None:
            return None
        now = e.clock.now()
        o = oc.make(kind, why)
        e.fp = o.fingerprint
        history: list[Any]
        try:
            history = self.o.loop_health.recent_closes(self.o.config_dir / "traces.jsonl", self.repo_id(), now)
        except OSError:
            history = []
        e.disp = oc.apply(o, e.bead, history, now)
        e.kind = e.disp.kind
        if e.disp.escalated:
            e.warn(f"the same fault {oc.KNOBS['fault_retries']} times on this bead: asking the owner once")
        self.storm(history, kind, o, why)
        return e.kind

    def storm(self, history: Any, kind: Any, o: Any, why: str) -> None:
        e, lh = self.e, self.o.loop_health
        trip = lh.storm_trip(history, e.bead, kind, o.fingerprint, e.clock.now())
        if trip and not e.dry:
            path = lh.storm_path(self.o.config_dir, self.repo_id())
            if lh.write_storm(path, trip, e.clock.now(), why):
                e.storm = lh.banner(trip)
                e.warn(e.storm)
                self.o.say(e.storm)

    def run(self, outcome: str, why: str, sha: str, spec: Any, kind: Any = None) -> None:
        e, oc = self.e, self.o.oc
        why = why or ("stopped before a reason was recorded" if outcome == "failed" else "")
        bad = (raiser.problems(spec) if spec else ["the stop carries no ask"]) if kind in oc.ASKS else []
        if bad:  # an ask that is no ask an owner can answer is the engine's own fault; no prose question takes its place
            first = why.splitlines()[0][:200] if why else ""
            why, kind, spec = f"failed: ask_lint: {'; '.join(bad)[:300]} ({first})", oc.Kind.FAULT_ENGINE, None
        kind = self.decide(outcome, why, kind)
        outcome = self.o.outcome_for(kind, why) if kind and kind not in oc.FINISH else outcome
        if e.disp and e.disp.escalated and spec is None:
            spec = askspecs.repeated_fault(oc.KNOBS["fault_retries"], why.splitlines()[0][:200])
        new = fu.batch(e.bead, e.leftovers, e.filed).file  # one per typed key, at most the cap
        self.save_branch(outcome, why)
        counts = "; ".join(f"{k}={v}" for k, v in e.stats.items())
        stats = f"cost=${e.cost:.2f}; minutes={int((time.time() - e.t0) / 60)}; {counts}"
        self.record(outcome, why, sha, spec, kind, stats)
        if e.dry:
            e.log.note(f"dry run: bead left as it was. {stats}")
            return
        if kind == oc.Kind.WAIT_ASK or (kind is None and why.startswith("waiting:")):  # asked already: the bead stays as the ask left it
            e.log.note(why)
            return
        e.asked = bool(kind in oc.ASKS and spec and outcome not in DONE and e.raise_ask(spec, why, kind))
        lost = self.follow_ups(outcome)
        self.reflect_comment(outcome, why, new, lost, stats)
        self.settle(outcome, why, sha, spec, kind, stats)

    def save_branch(self, outcome: str, why: str) -> None:
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

    def record(self, outcome: str, why: str, sha: str, spec: Any, kind: Any, stats: str) -> None:
        """The run's log and trace: the close node, the reflection, the owner's question."""
        e, o = self.e, self.o
        e.log_run()
        last = e.steps.cur or e.steps.last
        if last and (e.steps.moved_from != last.n or e.steps.moved_to not in ("ask", "pause", "close")):
            to, cause = o.close_move(outcome, why, kind)  # no move out of the run was logged from the last node: the close is it
            e.steps.move(to, cause, why.splitlines()[0][:200] if why else outcome)
        e.steps.end(o.node_outcome(outcome, why, kind))
        e.steps.begin("close", f"close: {outcome}")
        code = o.why_code(kind.value if kind else "", outcome)
        e.log.emit(rec.Close(outcome=Outcome(outcome), why_code=code, sha=sha or "", why=why[:500]))
        e.steps.outcome(outcome, why.splitlines()[0][:200] if why else "")
        e.steps.end()
        e.reflection = e.reflect_run(outcome, why)  # after the close node: the outcome is decided and nothing here changes it
        e.file_trace(outcome, why, sha)
        e.detail([stats] + ([why[:400]] if why else []) + (["question: " + spec.decision[:400]] if spec else []))
        if outcome == "failed":
            e.warn(f"task failed: {why.splitlines()[0][:200]}")

    def follow_ups(self, outcome: str) -> list[dict[str, str]]:
        """Landed work leaves its notes: the ask closed, the unverified items and the unchecked look items said, evidence kept, and each
        follow-up filed as a bead (what bd refuses is kept in the checkpoint, none lost)."""
        e = self.e
        if outcome in DONE:
            old = e.stores.asks.get(e.bead)
            if old:
                e.stores.asks.close(e.bead, old.id, "the run landed")
            if e.unverified:
                e.comment("Land (engine): " + e.owner_look.unverified_text())
            look = [u for u in e.unchecked if u["kind"] == "other" and not e.judge.is_look(u)]
            if look:
                self.o.attempt(e.store.add_label, e.bead, "needs-owner-check")
                e.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = e.pictures.keep_evidence()
        if shots:
            e.comment("Evidence (engine): " + ", ".join(str(p) for p in shots))
        lost = file_follow_ups(e)
        if outcome == "landed":
            e.owner_look.file_owner_look()
        return lost

    def reflect_comment(self, outcome: str, why: str, new: list[Any], lost: list[Any], stats: str) -> None:
        e = self.e
        verified = ""
        if e.verified:
            verified = "; self-verified=" + ", ".join("{} {}".format(sum(x["verdict"] == k for x in e.verified), k) for k in VERDICTS)
        unfiled = f" unfiled={len(lost)};" if lost else ""
        text = self.o.reflection_text(e.reflection)
        e.comment(f"Reflect (engine): outcome={outcome};{text} filed={len(new) - len(lost)};{unfiled} {stats}"
                  f"{verified}{('; why=' + why) if why else ''}; trace={e.log_path.stem} (tl trace {e.bead})")

    def settle(self, outcome: str, why: str, sha: str, spec: Any, kind: Any, stats: str) -> None:
        """The bead's status: closed (landed or done), left open (a machine fault or a pause) or blocked on the owner."""
        e, oc, track = self.e, self.o.oc, self.o.track
        summary = e.plan_summary[:300]
        if outcome == "landed":
            base = e.cfg.base.split("/")[-1]
            rc = track.close(e.bead, f"merged {sha[:12]} to {base}: {summary or 'the task stages passed'}; {stats}", e.store)
        elif outcome == "done":
            rc = track.close(e.bead, "done with nothing to land: " + (summary or stats), e.store)
        elif kind and oc.POLICY[kind].bd == "open":  # a machine fault or pause: the bead stays open, unassigned
            rc = self.leave_open(kind, why)
        else:
            rc = track.block(e.bead, why + (("\n\nQuestion: " + spec.decision) if spec else ""), e.store)
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            e.warn(f"bd refused to {'block' if outcome not in DONE else 'close'} {e.bead} (exit {rc}): close it by hand")

    def leave_open(self, kind: Any, why: str) -> int:
        e, oc = self.e, self.o.oc
        fault = kind.name.startswith("FAULT_")
        if not fault:
            e.warn(why)
        rc = 0 if self.o.attempt(e.store.update, e.bead, BeadPatch(status="open", assignee="")) else 1  # (tl-kwo: it lets go)
        if oc.POLICY[kind].label:
            self.o.attempt(e.store.add_label, e.bead, oc.POLICY[kind].label)
        if e.disp.comment:  # a comment, never Notes (tl-7y6.6.2); one per (bead, kind, fingerprint) per hour
            e.comment("Engine {}: {}".format("failed" if fault else "paused", without_prefix(why)[:400]))
        return rc
