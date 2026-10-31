"""The ask a run waits on or files: an open ask is never asked again; a stop that carries one files it; the review cap."""
import time
from typing import Any

from taskloop.app.asks import raiser
from taskloop.app.run.blocked import Blocked
from taskloop.app.run.layout import repo_of
from taskloop.contracts.kinds import Kind
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks import text as asktext


class AskFlow:
    def __init__(self, host: Any) -> None:
        self.e = host

    def check(self) -> None:
        """An open ask is never asked again: with the bead unchanged the run waits; a change (the owner's comment or edit) or a
        filed answer answers it, and the run goes on from its checkpoint."""
        e = self.e
        state, a = raiser.check(e.stores.asks, e.bead, e.brief_hash, e.fresh, time.time())
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

    def raise_ask(self, spec: Any, why: str, kind: Any) -> Any:
        """File the ask the stop carries. Lint decides whether it is one an owner can answer: if not, nothing is filed and the stop is
        the engine's own fault, never a prose question. -> the Ask, or None."""
        e = self.e
        at = raiser.Asking(bead=e.bead, run=e.run_id, brief_hash=e.brief_hash, now=time.time(), why=why, repo=self.repo(),
                           title=e.bead_title)
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

    def review_cap(self) -> None:
        """A run's reviews are counted once for the whole run, a replan does not start them again (engine.max_total_reviews)."""
        e = self.e
        cap = int(e.cfg.max_total_reviews)
        if cap and e.stats["reviews"] > cap:
            hint = e.stuck_why[:600]
            n = e.stats["reviews"]
            raise Blocked(f"{n} reviews in this run (the limit is {cap}, replans included): it needs the owner's hint\n{hint}",
                          askspecs.open_question(f"{n} reviews ran in this run (the limit is {cap}, replans included). {hint}", None),
                          kind=Kind.ASK_STUCK)
