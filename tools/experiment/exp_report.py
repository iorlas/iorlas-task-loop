"""Results JSON and the markdown report skeleton. Pure: results in, text out; the numbers are read, never judged here."""

import statistics
from collections.abc import Callable

from exp_spec import Outcome, RunResult, Spec

type Row = dict[str, object]


def number(row: Row, key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def known(rows: list[Row], key: str) -> bool:
    return all(isinstance(row.get(key), (int, float)) for row in rows)


def step_rows(result: RunResult, step: str) -> list[Row]:
    return [row for row in result.export if row.get("step") == step]


def total(result: RunResult, key: str, step: str | None = None) -> float | None:
    rows = result.export if step is None else step_rows(result, step)
    return sum(number(row, key) for row in rows) if rows and known(rows, key) else None  # unknown is not zero


def uncached(result: RunResult) -> float | None:
    inputs, cached = total(result, "t_in"), total(result, "t_cached")
    return None if inputs is None or cached is None else inputs - cached


def task_seconds(result: RunResult) -> float | None:
    values = [number(row, "task_total_seconds") for row in result.export if isinstance(row.get("task_total_seconds"), (int, float))]
    return max(values) if values else None


def repeats(result: RunResult) -> int:
    return int(sum(number(row, "rework_count") for row in result.export if row.get("step") == "implement") > 0) if result.export else 0


METRICS: tuple[tuple[str, Callable[[RunResult], float | None]], ...] = (
    ("task total s", task_seconds),
    ("plan wall s", lambda r: total(r, "wall_seconds", "plan")),
    ("implement wall s", lambda r: total(r, "wall_seconds", "implement")),
    ("input uncached", uncached),
    ("input cached", lambda r: total(r, "t_cached")),
    ("input total", lambda r: total(r, "t_in")),
    ("output", lambda r: total(r, "t_out")),
    ("plan input uncached", lambda r: _uncached_step(r, "plan")),
    ("implement input uncached", lambda r: _uncached_step(r, "implement")),
    ("model requests", lambda r: total(r, "turns")),
)


def _uncached_step(result: RunResult, step: str) -> float | None:
    inputs, cached = total(result, "t_in", step), total(result, "t_cached", step)
    return None if inputs is None or cached is None else inputs - cached


def summary(values: list[float]) -> str:
    """n, mean, median, sd (sample; `-` below two values). Runs with an unknown value are left out, and n says how many."""
    if not values:
        return "n=0"
    sd = f"{statistics.stdev(values):,.0f}" if len(values) > 1 else "-"
    return f"n={len(values)} mean {statistics.fmean(values):,.0f} median {statistics.median(values):,.0f} sd {sd}"


def run_table(results: list[RunResult]) -> str:
    head = (
        "| run | block | arm | outcome | task s | input uncached | input cached | output | requests | repeats | failed checks |\n"
        + "|---" * 11
        + "|"
    )
    lines = [head]
    for r in results:
        cells = [_cell(fn(r)) for _name, fn in (METRICS[0], METRICS[3], METRICS[4], METRICS[6], METRICS[9])]
        failed = sorted(failed_checks(r))
        lines.append(
            f"| {r.run.name} | {r.run.block} | {r.run.arm} | {r.outcome} | "
            + " | ".join(cells)
            + f" | {repeats(r)} | {', '.join(failed) or '-'} |"
        )
    return "\n".join(lines)


def failed_checks(result: RunResult) -> set[str]:
    names: set[str] = set()
    for row in result.export:
        listed = row.get("failed_checks")
        if isinstance(listed, list):
            names.update(str(name) for name in listed)
    return names


def _cell(value: float | None) -> str:
    return "?" if value is None else f"{value:,.0f}"


def arm_table(results: list[RunResult], arms: list[str]) -> str:
    lines = ["| metric | " + " | ".join(arms) + " |", "|---" * (len(arms) + 1) + "|"]
    for name, fn in METRICS:
        cells = []
        for arm in arms:
            values = [v for r in results if r.run.arm == arm and r.outcome is Outcome.PASS and (v := fn(r)) is not None]
            cells.append(summary(values))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def denominators(results: list[RunResult], arms: list[str]) -> str:
    """Repeats are the denominator of any feedback comparison; holds and caps count as results, never dropped."""
    lines = [
        "| arm | runs | pass | held | incomplete | capped | infra | runs with a failed-check repeat |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        mine = [r for r in results if r.run.arm == arm]
        counts = [
            sum(r.outcome is o for r in mine) for o in (Outcome.PASS, Outcome.HELD, Outcome.INCOMPLETE, Outcome.CAP_WALL, Outcome.INFRA)
        ]
        lines.append(f"| {arm} | {len(mine)} | " + " | ".join(map(str, counts)) + f" | {sum(repeats(r) for r in mine)} |")
    return "\n".join(lines)


def report(spec: Spec, results: list[RunResult], order: str) -> str:
    arms = list(spec.arms)
    frozen = "\n".join(f"- arm `{name}`: workflow `{arm.workflow}`, efforts {arm.efforts or 'default'}" for name, arm in spec.arms.items())
    base = (
        f"- base commit `{spec.base}`; seed {spec.seed}; {spec.in_flight} in flight; "
        f"wall cap {spec.wall_minutes} min; attempt {spec.attempt_minutes} min"
    )
    return "\n".join(
        [
            f"# {spec.name}: report",
            "",
            "Status: skeleton generated by `tools/experiment`; the Question, Setup notes and Findings are the author's to write.",
            "",
            "## Question",
            "",
            "TODO",
            "",
            "## Frozen",
            "",
            base,
            frozen,
            "- tasks: " + ", ".join(task.id for task in spec.tasks),
            "",
            "## Order (blocks of one run per arm)",
            "",
            "```",
            order.rstrip(),
            "```",
            "",
            "## Runs",
            "",
            run_table(results),
            "",
            "## Outcomes and repeats (the denominators)",
            "",
            denominators(results, arms),
            "",
            "## Per arm, passed runs only",
            "",
            "Unknown values are left out (n says how many); uncached input is input minus cached; plan and implement are separate rows.",
            "",
            arm_table(results, arms),
            "",
            "## Findings",
            "",
            "TODO: read every number as exploratory; compare against the A/A noise before claiming a difference.",
            "",
        ]
    )
