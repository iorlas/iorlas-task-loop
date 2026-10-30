"""What the engine says about its checks: lines of a round, a result as a prompt row, the failing checks as a brief, the engine's own
results as evidence a reader may cite."""
from collections.abc import Sequence
from pathlib import Path
from typing import assert_never

from taskloop.contracts.checks import UNVERIFIED_EXIT, CheckResult, CheckRun
from taskloop.domain.checks import diagnostics, matchers, trim
from taskloop.domain.checks.diagnostics import CheckDiagnostics
from taskloop.domain.checks.names import norm


def mark_of(c: CheckResult) -> str:
    """The sign before a check's line, one per verdict."""
    match c.status:
        case "passed":
            return "✓"
        case "failed":
            return "✗"
        case "skipped":
            return "\u2013"
        case "unverified":
            return "?"
        case never:
            assert_never(never)


def _because(c: CheckResult) -> str:
    if c.status == "unverified":
        return f" (unverified: exit {UNVERIFIED_EXIT} means the check could not verify; it is not a pass)"
    if c.why:
        return f" ({c.why})"
    if c.cached:
        return " (%s)" % (c.note or "same tree and base: earlier result")
    if c.reused:
        return " (same command ran earlier in this block)"
    return " (red on the untouched base too: not the writer's)" if c.base_red else ""


def round_lines(results: Sequence[CheckResult]) -> list[str]:
    """The round, one line per check, and a failed one's last lines under it."""
    out: list[str] = []
    for c in results:
        mark = mark_of(c)
        out.append("{} [{}] `{}` {}{}".format(mark, c.group, c.id, c.status if c.exit is None else f"exit {c.exit}", _because(c)))
        if c.status == "failed":
            out += c.tail.splitlines()[-3:]
    return out


def round_outcome(run: CheckRun) -> str:
    """The step's outcome text: what failed, or how many passed."""
    bad = run.failed
    if not bad:
        left = run.unverified
        return f"{len(run.passed)} passed" + (f", {len(left)} unverified: " + ", ".join(c.id[:60] for c in left) if left else "")
    return f"{len(bad)} failed: " + ", ".join(c.id[:60] for c in bad)


def compact(checks: Sequence[CheckResult]) -> str:
    """Check results for a prompt: command, exit code, and the lines that say what ran (a passing gate that skipped its Unity steps
    must not look like one that ran them), or the tail of a failure."""
    out = []
    for c in checks:
        if c.exit is None:
            out.append(f"- `{c.cmd}` skipped: {c.why}")
            continue
        lines = [ln.strip() for ln in c.tail.splitlines() if ln.strip()]
        if c.exit:
            body = " | ".join(x.strip() for x in trim.trim_log(c.tail, cap=600, tail_lines=3).splitlines())
        else:
            body = " | ".join([ln for ln in lines[:-1] if matchers.is_notable(ln)][-3:] + lines[-1:])[-300:]
        base = " (red on the untouched base too: not the writer's)" if c.base_red else ""
        out.append(f"- `{c.cmd}` exit {c.exit}{base}" + (": " + body if body else ""))
    return "\n".join(out) or "- (no checks)"


def diagnostics_of(checks: Sequence[CheckResult], run_dir: Path) -> list[CheckDiagnostics]:
    """What each failing check says, as records: its diagnostics read out of the saved log (the whole log, not the tail the result
    kept), else its words for the trimmer."""
    out: list[CheckDiagnostics] = []
    for c in checks:
        log = Path(run_dir, c.log) if c.log else None
        try:
            text = log.read_text(encoding="utf-8", errors="replace") if log and "diff" not in c.tags else c.tail
        except OSError:
            text, log = c.tail, None
        end = f"timed out after {int(c.secs)} s" if isinstance(c.exit, int) and (c.exit == 124 or c.exit < 0) else ""
        out.append(diagnostics.of_check(c.cmd, c.exit, text, str(log) if log else "none", end))
    return out


def failure_brief(checks: Sequence[CheckResult], run_dir: Path, each: int = trim.CAP, total: int = 3 * trim.CAP,
                  lines: int = trim.TAIL) -> str:
    """The failing checks for a prompt: command (cut at 300 chars), log path ("none" when no log), then each diagnostic the output
    holds (file:line:col, severity, rule, message; diagnostics.py), else the saved log trimmed by trim_log (failure lines with their
    context, plus its last `lines` lines), then a timeout note. Each check is at most `each` bytes in all, `total` for all checks;
    the full log stays on disk at the path given."""
    return diagnostics.render_all(diagnostics_of(checks, run_dir), each, total, lines)


def flagged_why(check: CheckResult, bad_checks: Sequence[dict[str, str]]) -> str:
    """The writer's reason when one of its bad_checks names this failed check, else "": by its command as listed, whitespace aside; by its
    id; or shortened (`...` for what it cut, or a stretch of 20+ characters of it)."""
    mine = norm(check.cmd)
    for b in bad_checks:
        said = norm(b["cmd"]).strip("`")
        if not said:
            continue
        if said in (mine, check.id):
            return b["why"]
        if matchers.names_shortened(said, mine):
            return b["why"]
    return ""


def timed_out(failed: Sequence[CheckResult]) -> CheckResult | None:
    """The first red check the engine stopped at its wall limit, else None. Such a check is parked on, never sent back to the writer."""
    return next((c for c in failed if c.wall_hit), None)


def timeout_why(c: CheckResult) -> str:
    """The reason a timed-out check parks the bead."""
    return f"check {c.id} timed out after {c.wall_min:g} min (wall_min={c.wall_min:g})"
