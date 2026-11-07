"""The close's outcome as the checkpoint keeps it (contracts EndRec), and the question a restart asks of it: is a close still unfinished?"""
import json
from collections.abc import Mapping, Sequence
from typing import Protocol

from tlkernel import runoutcome as oc
from tlkernel import wire
from tlkernel.ask import AskDetail, AskOption
from tlkernel.askenums import AskClass
from tlkernel.askspec import AskSpec
from tlkernel.checkpoint import Checkpoint, CloseIntent, EndRec, PauseFacts, Producer
from tlkernel.dash import OwnerCause
from tlkernel.delegate import Permanence
from tlkernel.kinds import Kind

from taskloop.domain import effects


def spec_text(spec: AskSpec | None) -> str:
    """The ask as JSON text, "" for none."""
    if spec is None:
        return ""
    return json.dumps({"ask_class": spec.ask_class.value, "decision": spec.decision, "tried": spec.tried,
                       "options": [o.to_dict() for o in spec.options], "detail": spec.detail.to_dict(),
                       "owner_cause": spec.owner_cause.value, "blocking": spec.blocking, "default": spec.default})


def spec_of(text: str) -> AskSpec | None:
    if not text:
        return None
    d = json.loads(text)
    return AskSpec(ask_class=AskClass(d["ask_class"]), decision=d["decision"], tried=list(d["tried"]),
                   options=[wire.load(AskOption, o) for o in d["options"]], detail=wire.load(AskDetail, d["detail"]),
                   owner_cause=OwnerCause(d["owner_cause"]), blocking=d["blocking"], default=d["default"])


def stored(run: str, done: oc.RunOutcome, disp: oc.Disposition | None, fp: str, leftovers: Sequence[Mapping[str, str]]) -> EndRec:
    """The final outcome and the decision POLICY made, as plain data."""
    return EndRec(run=run, kind=done.kind.value, fingerprint=done.fingerprint, detail=done.detail, sha=done.sha,
                  spec=spec_text(done.spec), fp=fp,
                  comment=disp.comment if disp else True, escalated=disp.escalated if disp else False,
                  leftovers=[dict(lo) for lo in leftovers])


def loaded(rec: EndRec) -> tuple[oc.RunOutcome, oc.Disposition, str]:
    """(the final outcome, its Disposition, the fingerprint before escalation)."""
    spec = spec_of(rec.spec)
    done = oc.RunOutcome(Kind(rec.kind), rec.fingerprint, rec.detail, sha=rec.sha, spec=spec)
    rule = done.rule
    return done, oc.Disposition(done.kind, rule.bd, rule.label, rule.loop, rule.trace, rule.makes_ask, rec.comment, rec.escalated), rec.fp


def unfinished(ck: Checkpoint | None) -> bool:
    """A run died inside its close: its checkpoint holds the outcome and a key of the plan is not applied."""
    if ck is None or ck.ended is None:
        return False
    done, _, _ = loaded(ck.ended.outcome)
    plan = effects.plan_close(done, dry=False, branch="", slot_gen=0)
    return any(effects.key_of(ck.bead, ck.ended.outcome.run, eff) not in ck.applied for eff in plan)


class HostFacts(Protocol):
    """Only the host facts the close must keep across an engine restart."""

    pause_reason: str
    pause_producer: Producer
    pause_permanence: Permanence | None
    retry_after: float
    crash_fingerprint: str
    crash_site: str
    plan_summary: str
    asked: bool


def intent_of(end: EndRec, host_facts: HostFacts, stats: str) -> CloseIntent:
    """Keep the final pause facts and the already built stats beside the outcome."""
    h = host_facts
    return CloseIntent(outcome=end, pause=PauseFacts(reason=h.pause_reason, producer=h.pause_producer,
                       permanence=h.pause_permanence, retry_after=h.retry_after,
                       crash_fingerprint=h.crash_fingerprint, crash_site=h.crash_site),
                       stats=stats, plan_summary=h.plan_summary, asked=h.asked)
