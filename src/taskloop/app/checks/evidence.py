"""What the engine says about its checks: lines of a round, a result as a prompt row, the failing checks as a brief, the engine's own
results as evidence a reader may cite."""
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType

from taskloop.contracts.checks import CheckResult, CheckRun
from taskloop.domain.checks import matchers, trim
from taskloop.domain.checks.names import norm
from taskloop.domain.checks.specs import DIFF_CHECK

MARKS = MappingProxyType({"passed": "✓", "failed": "✗", "skipped": "\u2013"})


def _because(c: CheckResult) -> str:
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
        mark = MARKS[c.status]
        out.append("{} [{}] `{}` {}{}".format(mark, c.group, c.id, c.status if c.exit is None else f"exit {c.exit}", _because(c)))
        if c.status == "failed":
            out += c.tail.splitlines()[-3:]
    return out


def round_outcome(run: CheckRun) -> str:
    """The step's outcome text: what failed, or how many passed."""
    bad = run.failed
    if not bad:
        return f"{len(run.passed)} passed"
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


def failure_brief(checks: Sequence[CheckResult], run_dir: Path, each: int = trim.CAP, total: int = 3 * trim.CAP,
                  lines: int = trim.TAIL) -> str:
    """The failing checks for a prompt: command (cut at 300 chars), log path ("none" when no log), then the saved log trimmed by
    trim_log (failure lines with their context, plus its last `lines` lines), then a timeout note. Each check is at most `each`
    bytes in all, `total` for all checks; the full log stays on disk at the path given."""
    out: list[str] = []
    left = total
    for c in checks:
        log = Path(run_dir, c.log) if c.log else None
        try:
            text = log.read_text(encoding="utf-8", errors="replace") if log and c.id != DIFF_CHECK else c.tail  # its tail is already capped
        except OSError:
            text, log = c.tail, None
        end = ""
        if isinstance(c.exit, int) and (c.exit == 124 or c.exit < 0):
            end = f"timed out after {int(c.secs)} s"
        cmd = c.cmd if len(c.cmd) <= 300 else c.cmd[:300] + "..."
        head = "- `{}` exit {}\n  log: {}".format(cmd, c.exit, log or "none")
        room = min(each, left)
        if room <= len(head) + 80:
            out.append(head + "\n  (output left out: see the log)")
            continue
        body = trim.trim_log(text, cap=room - len(head.encode("utf-8")) - len(end) - 2, tail_lines=lines)
        text = "\n".join(x for x in (body, end) if x)
        left -= len(head.encode("utf-8")) + len(text.encode("utf-8")) + 1
        out.append(head + ("\n" + text if text else ""))
    return "\n".join(out) or "- (no checks)"


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
