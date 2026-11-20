"""One preparation result for status readers and hold decisions."""

from taskloop.attempt_types import AttemptResult
from taskloop.merge.models import PREFIX, Phase, Reason
from taskloop.merge.store import MergeStore


def result(store: MergeStore, attempt_id: str, now: float) -> AttemptResult | None:
    work = store.get(attempt_id)
    if work is None or work.phase is Phase.COMPLETE:
        return None
    if work.phase is Phase.TERMINAL or now >= work.deadline:
        reason = work.reason or Reason.EXPIRED
        detail = work.explanation if work.phase is Phase.TERMINAL else "Main's merge reached its deadline; retained work is held."
        return AttemptResult("refused", PREFIX + reason, explanation=detail)
    execution = work.executions[-1] if work.executions else None
    session = "" if execution is None else f" Resolution execution {execution.number}, session {execution.session or 'not yet known'}."
    return AttemptResult("pending", PREFIX + Reason.RUNNING, explanation=work.explanation + session)
