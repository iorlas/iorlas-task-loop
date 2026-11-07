"""The re-plan cap: when the planner has run too often the bead asks the owner; the owner's answer (or an override on the bead)
allows one more run."""


from taskloop.app.asks import intake
from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.host import PlanHand, PlanPorts
from taskloop.app.plan.prompts import REPLAN_CAP
from taskloop.app.plan.state import PlanState
from tlkernel.bdsafe import attempt, peek
from tlkernel.bead import Bead
from tlkernel.beadsport import BeadPatch
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import AskClass
from tlkernel.stagefacts import RunFacts
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks import text as asktext


class ReplanCap:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand

    def blocked(self, detail: str = "") -> Exception:
        """The cap's ask: the planner ran `planned` times. An answer that allows one more (action rerun) gives one."""
        runs = [(x.mode, x.why) for x in self.hand.plan_log]
        why = "; ".join(f"{k + 1}. {m}: {w}" for k, (m, w) in enumerate(runs))[:1500]
        limit = self.facts.cfg.max_replans + self.hand.extra
        text = f"{REPLAN_CAP}{self.hand.planned} times (the limit is 1 plan + {limit} amends): {why}{('; ' + detail) if detail else ''}"
        return self.ports.blocked_for(text, "ASK_STUCK", spec=askspecs.cap_reached(self.hand.planned, runs))

    def grant(self) -> None:
        """The owner allows one more planner run: they answered the cap's ask with the rerun option, or put the override on the bead
        (`tl override BEAD replan-cap`). Any other answer is recorded and the bead blocks again at the cap. The grant goes into the
        checkpoint's extra, which the resume adds to."""
        a = self.hand.answered
        by_ask = a is not None and a.ask_class == AskClass.CAP_REACHED
        bead = peek(self.ports.store, self.facts.bead) or Bead(id=self.facts.bead, title="", status="")
        by_override = bead.metadata.get(intake.OVERRIDE) == "replan-cap"
        if self.plan_state.cap_granted or not (by_ask or by_override):
            return
        self.plan_state.cap_granted = True
        rerun = a is not None and a.answer is not None and a.answer.action == "rerun"
        said = a.id if a else ""
        if not (by_override or rerun):
            self.ports.log.note(
                f"the owner answered the re-plan cap ({said}) without allowing more: still blocked. Answer: "
                f"{(self.answered_words() or '(none)')[:300]}"
            )
            return
        self.ports.log.note("the owner allowed one more planner run (%s)" % ("the override" if by_override else "ask " + said))
        if by_override:
            attempt(self.ports.store.update, self.facts.bead, BeadPatch(unset_metadata=[intake.OVERRIDE]))
        self.add_to_checkpoint()

    def add_to_checkpoint(self) -> None:

        def one_more(ck: Checkpoint) -> Checkpoint:
            return ck.replace(state=ck.state.replace(extra=ck.state.extra + 1))

        if not self.ports.checkpoints.amend(one_more):
            self.hand.extra += 1

    def answered_words(self) -> str:
        """What the owner's answer asks the work to do: their text, or the split instruction; a bare rerun or confirm asks for nothing."""
        return asktext.words(self.hand.answered.answer if self.hand.answered else None)

    def kept_whole(self) -> bool:
        """The owner answered the too-big ask, and not with 'I will split it': the plan goes ahead with all its stages."""
        a = self.hand.answered
        return a is not None and a.ask_class == AskClass.TOO_BIG and (a.answer is None or a.answer.action != "split")
