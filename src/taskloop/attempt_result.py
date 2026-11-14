"""Collect a stored attempt: its end word, verdict words and whether it succeeded. Read-only; no IO of its own."""

from dataclasses import replace

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, ExecutionFacts, Rejected, StoredExecution, Verdict


def end_word(stored: StoredExecution) -> str:
    """The run's own end word, fixed words only: `run:<classified reason>` for a failed or timed-out run, else `answer:<kind>`
    for an unusable answer, else the valid answer's disposition (`planned` and `unchanged` go on to verification)."""
    facts, answer = stored.facts, stored.answer
    if facts.timed_out or facts.rc != 0:
        return "run:" + (facts.reason or ("timeout" if facts.timed_out else "exit"))
    if answer.kind != "valid" or answer.disposition is None:
        return "answer:" + answer.kind
    return answer.disposition


def committing(stored: StoredExecution) -> bool:
    """A clean run's valid answer whose effect the factory commits (`commit`) or keeps (`keep`): only such a result goes
    on to verification; its end word is its disposition."""
    facts, answer = stored.facts, stored.answer
    return not facts.timed_out and facts.rc == 0 and answer.kind == "valid" and answer.effect in ("commit", "keep")


def usage_explanation(facts: ExecutionFacts) -> str:
    """Describe missing stream usage without inventing counts or completeness."""
    counts = (*(facts.tokens or (None, None, None)), facts.turns)
    cumulative = facts.cumulative or (None, None, None)
    words = []
    if facts.usage_incomplete is True:
        words.append("Usage is incomplete: the in-flight request is missing.")
    if all(value is None for value in (*counts, *cumulative)):
        words.append("Usage was not reported by the agent stream.")
    else:
        labels = ("input tokens", "cached input tokens", "output tokens", "turns")
        missing = [label for label, value in zip(labels, counts, strict=True) if value is None]
        if facts.cumulative is not None:
            missing.extend("cumulative " + label for label, value in zip(labels[:3], cumulative, strict=True) if value is None)
        if missing:
            words.append("Usage was not reported for: " + ", ".join(missing) + ".")
    return " ".join(words)


def report(stored: StoredExecution) -> AttemptResult:
    result = _report(stored)
    usage = usage_explanation(stored.facts)
    return replace(result, explanation=" ".join((result.explanation or result.reason, usage))) if usage else result


def _report(stored: StoredExecution) -> AttemptResult:
    """Stored terminal data is collected with its end word; a pending validation, session state or verification is
    never complete. An answer of effect `commit` or `keep` (`planned`, `unchanged`) is collected only with its verdict:
    `verified`, `reused` or `rejected:<rule>`."""
    if stored.answer.kind == "validation_pending":
        return AttemptResult("pending", "validation_pending", stored)
    if stored.session_state == "conflict":
        return AttemptResult("conflict", "session", stored)
    if stored.session_state != "complete":
        return AttemptResult("pending", "session_" + stored.session_state, stored)
    reason, verdict = end_word(stored), stored.verification
    if not committing(stored):
        failure = stored.answer.failure
        explanation = failure.describe() if reason.startswith("answer:") and failure is not None else ""
        return AttemptResult("collected", reason, stored, explanation=explanation)
    if verdict is None:
        return AttemptResult("pending", "verification", stored)
    return AttemptResult("collected", judged(verdict), stored)


def judged(verdict: Verdict) -> str:
    """A verdict in fixed words: `verified` (new work), `reused` (an existing plan) or `rejected:<rule>`."""
    if isinstance(verdict, Rejected):
        return "rejected:" + verdict.reason
    return "reused" if verdict.reused else "verified"


def succeeded(result: AttemptResult) -> bool:
    """`collected` means terminal, never success: success is a verified step result, new (`verified`) or existing
    (`reused`), or a checks attempt concluded `passed` (`check_status.checks_result`)."""
    return result.status == "collected" and result.reason in ("verified", "reused", "passed")


def collect(store: AttemptStore, key: AttemptKey) -> AttemptResult:
    """Read-only: stored facts need no reservation, input, credential or remaining deadline."""
    try:
        stored = store.collect(key)
        if stored is not None:
            return report(stored)
        state = store.state(key)
    except StoreUnavailable:
        return AttemptResult("unavailable", "collect")
    if state is None:
        return AttemptResult("refused", "absent")
    return AttemptResult("conflict", "session") if state[1] else AttemptResult("pending", state[0])
