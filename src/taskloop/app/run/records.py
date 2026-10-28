"""What a run records about itself: why it started, its run record in the engine log, its line in traces.jsonl."""
import time
from typing import Any

from taskloop.adapters import ident
from taskloop.app.run import trace as runtrace
from taskloop.app.slots import engine_lock
from taskloop.contracts import log as rec
from taskloop.domain.report import matchers as lifecycle


class Records:
    def __init__(self, host: Any) -> None:
        self.e = host

    def origin(self) -> dict[str, str]:
        """Why this run started and the run before it: the checkpoint's run when there was one, else the bead's previous
        engine log. answer: an owner's answer to an ask; resume: the checkpoint was used; retry: an earlier run, no
        checkpoint used; fresh: --fresh; first: no earlier run."""
        e = self.e
        prev = e.ck_run or e.prev_ck
        if not prev:
            mine = e.log_path.name
            older = sorted(p.stem for p in e.log_path.parent.glob(f"{e.bead}-*.jsonl")
                           if p.name < mine and lifecycle.is_run_stamp(p.stem[len(e.bead) + 1:]))
            prev = older[-1] if older else ""
        why = ("reexec" if e.reexec else "fresh" if e.fresh else "answer" if e.answered else "resume" if e.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": lifecycle.normalize_started_because(why, prev),
                "ask": e.answered.id if e.answered else ""}

    def log_run(self) -> None:
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        e = self.e
        if e.run_logged:
            return
        e.run_logged = True
        if e.reexec:  # the run record is in the log already (the exec kept the log): a note says what happened
            fallback = " (fallback after a crash)" if e.reexec.get("fallback") else ""
            e.log.note(f"task-loop {ident.plugin_version() or '?'} took over run {e.log_path.stem} from {e.reexec.get('from')}{fallback}")
            return
        lock = engine_lock.LOCK
        why = self.origin()
        e.log.emit(rec.RunStart(run=e.log_path.stem, bead=e.bead, worktree=str(e.wt), slot=(lock.data.get("slot") if lock else "") or None,
                                prev_run=why["prev_run"], started_because=why["started_because"], ask=why["ask"]))

    def file_trace(self, outcome: str, why: str, sha: str) -> None:
        """One line per engine run in traces.jsonl, never pruned: bead, repo, branch, every session, the outcome."""
        e = self.e
        kind = e.kind.value if e.kind else ""
        try:
            e.stores.traces.append(runtrace.run_trace(e.log_path.stem, dict(
                self.origin(), bead=e.bead, repo_url=e.git("remote", "get-url", "origin") or str(e.wt), worktree=str(e.wt),
                branch=e.git("symbolic-ref", "--short", "-q", "HEAD"), coordinator_session=e.session, version=ident.plugin_version(),
                started=e.t0, ended=time.time(), outcome=outcome, why=(why or "")[:500], sha=sha or "", kind=kind, kfp=e.fp,
                why_code=runtrace.why_code(kind, outcome), fingerprint=lifecycle.run_fingerprint(outcome, why), cost=e.cost,
                stats=e.stats, delegate_path=e.route or "", log=str(e.log_path), stderr=str(e.err_path),
                sessions=e.sessions, verified=e.verified, write_rounds=e.write_rounds, strays=e.strays,
                reflection=e.reflection, lane_notes=e.lane_notes, salvaged=e.salvaged)))
        except (OSError, ValueError) as err:
            e.warn(f"could not write the trace: {err}")
