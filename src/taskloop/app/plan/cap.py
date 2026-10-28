"""The re-plan cap: when the planner has run too often the bead asks the owner; the owner's answer (or an override on the bead)
allows one more run."""

import dataclasses
from typing import Any

from taskloop.adapters.bdsafe import attempt, peek
from taskloop.app.asks import intake
from taskloop.contracts.bead import Bead
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.enums import AskClass
from taskloop.contracts.ports import BeadPatch
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks import text as asktext
from taskloop.domain.prompts.plan import REPLAN_CAP


class ReplanCap:
    def __init__(self, host: Any) -> None:
        self.e = host

    def blocked(self, detail: str = "") -> Exception:
        """The cap's ask: the planner ran `planned` times. An answer that allows one more (action rerun) gives one."""
        e = self.e
        runs = [(x["mode"], x["why"]) for x in e.plan_log]
        why = "; ".join(f"{k + 1}. {m}: {w}" for k, (m, w) in enumerate(runs))[:1500]
        limit = int(e.cfg.max_replans) + e.extra
        text = f"{REPLAN_CAP}{e.planned} times (the limit is 1 plan + {limit} amends): {why}{('; ' + detail) if detail else ''}"
        return e.blocked_for(text, "ASK_STUCK", spec=askspecs.cap_reached(e.planned, runs))

    def grant(self) -> None:
        """The owner allows one more planner run: they answered the cap's ask with the rerun option, or put the override on the bead
        (`tl override BEAD replan-cap`). Any other answer is recorded and the bead blocks again at the cap. The grant goes into the
        checkpoint's extra, which the resume adds to."""
        e = self.e
        a = e.answered
        by_ask = a is not None and a.ask_class == AskClass.CAP_REACHED
        bead = peek(e.store, e.bead) or Bead(id=e.bead, title="", status="")
        by_override = bead.metadata.get(intake.OVERRIDE) == "replan-cap"
        if e.cap_granted or not (by_ask or by_override):
            return
        e.cap_granted = True
        rerun = a is not None and a.answer is not None and a.answer.action == "rerun"
        said = a.id if a else ""
        if not (by_override or rerun):
            e.log.note(
                f"the owner answered the re-plan cap ({said}) without allowing more: still blocked. Answer: "
                f"{(self.answered_words() or '(none)')[:300]}"
            )
            return
        e.log.note("the owner allowed one more planner run (%s)" % ("the override" if by_override else "ask " + said))
        if by_override:
            attempt(e.store.update, e.bead, BeadPatch(unset_metadata=[intake.OVERRIDE]))
        self.add_to_checkpoint()

    def add_to_checkpoint(self) -> None:
        e = self.e

        def one_more(ck: Checkpoint) -> Checkpoint:
            return dataclasses.replace(ck, state=dataclasses.replace(ck.state, extra=ck.state.extra + 1))

        if not e.checkpoints.amend(one_more):
            e.extra += 1

    def answered_words(self) -> str:
        """What the owner's answer asks the work to do: their text, or the split instruction; a bare rerun or confirm asks for nothing."""
        return asktext.words(self.e.answered.answer if self.e.answered else None)

    def kept_whole(self) -> bool:
        """The owner answered the too-big ask, and not with 'I will split it': the plan goes ahead with all its stages."""
        a = self.e.answered
        return a is not None and a.ask_class == AskClass.TOO_BIG and (a.answer is None or a.answer.action != "split")
