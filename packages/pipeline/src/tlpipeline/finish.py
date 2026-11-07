"""Engine values at the manifest's single terminal-write boundary."""
import json

from tlkernel import runoutcome as oc
from tlkernel import wire
from tlkernel.checkpoint import EndRec
from tlkernel.enums import Result
from tlkernel.kinds import Kind
from tlkernel.run import RunFinish, RunState
from tlpipeline import ended
from tlpipeline import trace as runtrace


def terminal_state(outcome: oc.RunOutcome) -> RunState:
    """The policy result's manifest state, chosen once with the rest of the finish."""
    return {Result.LANDED: RunState.DONE, Result.STAGED: RunState.DONE, Result.PARKED: RunState.PARKED,
            Result.PAUSED: RunState.STOPPED}.get(outcome.rule.loop, RunState.FAILED)


def answer(done: oc.RunOutcome, now: float, end: EndRec | None = None) -> RunFinish:
    kept = end or ended.stored("", done, None, done.fingerprint, [])
    stage = done.kind is Kind.STAGE  # a stage's answer keeps no close outcome: the next run must not finish a close from it
    return RunFinish(state=terminal_state(done), ended=now, outcome=done.word, result=done.rule.loop,
                     kind=done.kind.value, why=done.detail, sha=done.sha,
                     why_code=runtrace.why_code(done.kind.value, done.word), end="" if stage else json.dumps(wire.dump(kept)))


def stage_answer(done: oc.RunOutcome, now: float) -> RunFinish:
    """What a one-stage run ends with when nothing wrote its answer first: its own kind, never the close outcome of a bead."""
    return RunFinish(state=terminal_state(done), ended=now, outcome=done.word, result=done.rule.loop, kind=done.kind.value,
                     why=done.detail, sha=done.sha, why_code=runtrace.why_code(done.kind.value, done.word))


def outcome(record: RunFinish) -> oc.RunOutcome:
    if record.end:
        return ended.loaded(wire.load(EndRec, record.end))[0]
    return oc.make(Kind(record.kind), record.why, sha=record.sha)


def land_answer(now: float, why: str = "", sha: str = "", ok: bool = True) -> RunFinish:
    """What a `tl land` run ends with: landed (at `sha`), or the land fault with its reason."""
    return answer(oc.make(Kind.LANDED if ok else Kind.FAULT_LAND, why, sha=sha), now)
