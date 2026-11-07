"""The ask a run waits on or files: an open ask is never asked again; a stop that carries one files it; the review cap."""
import time
from typing import Any

from tlartifacts import ask_pictures
from tlkernel.artifact import ArtifactSlot
from tlkernel.check_files import repo_key
from tlkernel.kinds import Kind

from taskloop.adapters import ident
from taskloop.app.asks import raiser, setup_retry
from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.run.layout import repo_of
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks import text as asktext


class AskFlow:
    def __init__(self, host: Any) -> None:
        self.e = host

    def check(self) -> None:
        """An open ask is never asked again: with the bead unchanged the run waits; a change (the owner's comment or edit) or a
        filed answer answers it, and the run goes on from its checkpoint."""
        e = self.e
        if not e.dry:
            setup_retry.retry_setup(e.stores.asks, e.store, e.bead, ident.plugin_version(), time.time(), e.cfg, starting=True)
        state, a = raiser.check(e.stores.asks, e.bead, e.state.brief_hash, e.fresh, time.time())
        if state == "wait" and a:
            raise Blocked(raiser.waiting_line(a), kind=Kind.WAIT_ASK)
        if state == "answer" and a:
            e.answered = a
            e.briefs.export()  # the brief the workers read now carries the owner's answer
            how = "the owner's answer is filed on it" if a.answer else "the bead changed since it was asked"
            e.log.note(f"ask {a.id} ({a.kind.value}) is answered: {how}")

    def repo(self) -> str:
        """The repo's path as asks and decisions name it: the parent of the git common dir (the worktree when git cannot say)."""
        return repo_of(self.e.git, self.e.wt)

    def pictures(self) -> list[str]:
        """The pictures the failing check left in this run, registered for the ask (none in a dry run)."""
        e = self.e
        if e.dry:
            return []
        e.artifact_repo = e.artifact_repo or repo_key(e.git, e.wt)
        slot = ArtifactSlot(repo=e.artifact_repo, bead=e.bead, run=e.run_id, stage="ask", attempt=1)
        return ask_pictures.attach(e.home.artifact_store(), slot, e.run_dir, now=time.time(), cap=int(e.cfg.evidence_cap_mb) << 20)

    def raise_ask(self, spec: Any, why: str, kind: Any) -> Any:
        """File the ask the stop carries. Lint decides whether it is one an owner can answer: if not, nothing is filed and the stop is
        the engine's own fault, never a prose question. -> the Ask, or None."""
        e = self.e
        at = raiser.Asking(bead=e.bead, run=e.run_id, brief_hash=e.state.brief_hash, now=time.time(), why=why, repo=self.repo(),
                           title=e.bead_title, artifacts=tuple(self.pictures()))
        a, problems = raiser.raise_ask(e.stores.asks, spec, at, e.stores.adrs(at.repo))
        if a is None:
            e.warn("the ask is not one an owner can answer ({}): {}".format("; ".join(problems), spec.decision[:200]))
            return None
        moved = raiser.leave_queue(e.store, e.bead, e.cfg.pick_label or "", e.cfg.needs_info_label or "") if (
            a.kind.value in ("decision", "ticket") and a.blocking and not e.dry) else ""
        e.comment(asktext.comment(a) + moved)
        return a

    def raise_soft(self, question: str, options: Any, cause: object, default: str) -> Any:
        """A question the agent may not block on (tl-ntp: a step that can be undone): the run goes on with `default`, and the ask is filed
        non-blocking, so the owner can still answer and the ledger counts it. Nothing is filed on a dry run."""
        if self.e.dry:
            return None
        return self.raise_ask(askspecs.open_question(question, options, cause, default), "", None)

    def review_cap(self, n: int) -> None:
        """A run's reviews are counted once for the whole run, a replan does not start them again (engine.max_total_reviews).
        `n`: the reviews of the run so far, the one about to start included."""
        e = self.e
        cap = int(e.cfg.max_total_reviews)
        if cap and n > cap:
            hint = e.stuck_why[:600]
            raise Blocked(f"{n} reviews in this run (the limit is {cap}, replans included): it needs the owner's hint\n{hint}",
                          askspecs.open_question(f"{n} reviews ran in this run (the limit is {cap}, replans included). {hint}", None),
                          kind=Kind.ASK_STUCK)
