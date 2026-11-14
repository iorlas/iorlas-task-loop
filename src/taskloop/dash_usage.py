"""Project persisted attempt usage once, then sum known values without inventing missing reports."""

from taskloop.attempt_types import ExecutionFacts
from taskloop.dash_model import AttemptDetail, Usage


def _count(value: int | None) -> int | None:
    return value if value is not None and value >= 0 else None


def project(facts: ExecutionFacts | None) -> Usage:
    whole, cached, output = (None, None, None) if facts is None or facts.tokens is None else facts.tokens
    whole, cached, output = _count(whole), _count(cached), _count(output)
    if whole is not None and cached is not None and cached > whole:
        whole = cached = None
    fresh = None if whole is None or cached is None else whole - cached
    turns = None if facts is None else _count(facts.turns)
    complete = int(all(each is not None for each in (fresh, cached, output, turns))
                   and (facts is None or facts.usage_incomplete is not True))
    return Usage(fresh, cached, output, turns, 1, complete)


def _sum(values: tuple[int | None, ...]) -> int | None:
    reported = tuple(each for each in values if each is not None)
    return sum(reported) if reported else None


def total(values: tuple[Usage, ...]) -> Usage:
    return Usage(_sum(tuple(each.fresh for each in values)), _sum(tuple(each.cached for each in values)),
                 _sum(tuple(each.output for each in values)), _sum(tuple(each.turns for each in values)),
                 sum(each.attempts for each in values), sum(each.complete for each in values))


def totals(attempts: tuple[AttemptDetail, ...]) -> tuple[dict[str, Usage], Usage]:
    by_step: dict[str, list[Usage]] = {}
    for attempt in attempts:
        if attempt.usage is not None:
            by_step.setdefault(attempt.step, []).append(attempt.usage)
    steps = {step: total(tuple(values)) for step, values in by_step.items()}
    return steps, total(tuple(steps.values()))
