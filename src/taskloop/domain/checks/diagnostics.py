"""The diagnostics of a red check, read out of its output (tl-9un.13). Pure: text in, records and text out.

A writer that cannot run a check (a Unity analyzer build its sandbox blocks) fixes only what the engine tells it, so the engine
tells it each diagnostic: where (file:line:col), the rule and the message, once, not a trimmed log. The formats are the tables of
diag/matchers.py (Roslyn/MSBuild, ruff, pyrefly, the generic `path:line:col: message`); output that holds none falls back to the
log trimmed to a byte cap (trim.trim_log), the command's own words."""
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from taskloop.domain.checks import trim
from taskloop.domain.checks.diag import matchers

ITEM_MAX: Final = 240  # a message longer than this is cut
TAIL_ROWS: Final = 4  # the command's last words kept under a list: its verdict line ("Build FAILED", "Found 3 errors")
MAX_ITEMS: Final = 60


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    col: int
    severity: str
    rule: str
    message: str

    def row(self) -> str:
        where = f"{self.path}:{self.line}" + (f":{self.col}" if self.col else "")
        what = " ".join(x for x in (self.severity, self.rule) if x)
        msg = self.message if len(self.message) <= ITEM_MAX else self.message[:ITEM_MAX - 3] + "..."
        return f"{where}: {what + ': ' if what else ''}{msg}"


@dataclass(frozen=True)
class CheckDiagnostics:
    """What one red check says: its diagnostics (when its output holds any), else `rest`, the trimmed output. `last`: its last
    words after a list; `note`: why it ended (a timeout)."""
    cmd: str
    exit: int | None
    log: str
    items: tuple[Diagnostic, ...] = ()
    rest: str = ""
    last: str = ""
    note: str = ""


def parse(text: object) -> list[Diagnostic]:
    """Every diagnostic of the output, once each, in the order the output says them (errors are not moved: the log's order is the
    build's)."""
    rows = [matchers.clean(ln) for ln in str(text or "").splitlines()]
    out: dict[Diagnostic, None] = {}
    i = 0
    while i < len(rows):
        raw = matchers.pair(rows[i], rows[i + 1]) if i + 1 < len(rows) else None
        step = 2
        if raw is None:
            raw, step = matchers.single(rows[i]), 1
        if raw is not None:
            out[Diagnostic(*raw)] = None
        i += step
    return list(out)


def _last_words(text: str) -> str:
    rows = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(trim.trim_log("\n".join(rows[-TAIL_ROWS:]), cap=600, tail_lines=TAIL_ROWS).splitlines())


def of_check(cmd: str, exit: int | None, text: str, log: str, note: str = "") -> CheckDiagnostics:
    """The check's diagnostics, or (none read) its output trimmed. The trim is sized at render time: `rest` here is the whole text."""
    items = parse(text)
    if items:
        return CheckDiagnostics(cmd=cmd, exit=exit, log=log, items=tuple(items), last=_last_words(text), note=note)
    return CheckDiagnostics(cmd=cmd, exit=exit, log=log, rest=text, note=note)


def render(c: CheckDiagnostics, room: int, tail_lines: int = trim.TAIL) -> str:
    """One check as prompt text within `room` bytes (a count of what was left out when the list does not fit)."""
    head = "- `{}` exit {}\n  log: {}".format(c.cmd if len(c.cmd) <= 300 else c.cmd[:300] + "...", c.exit, c.log or "none")
    if room <= len(head) + 80:
        return head + "\n  (output left out: see the log)"
    left = room - len(head.encode("utf-8")) - len(c.note) - 2
    if not c.items:
        body = trim.trim_log(c.rest, cap=left, tail_lines=tail_lines)
        return head + "".join("\n" + x for x in (body, c.note) if x)
    tail = (c.last + "\n" if c.last else "")
    rows: list[str] = []
    used = len(tail.encode("utf-8")) + 80  # room for "N more" and the tail
    for d in c.items[:MAX_ITEMS]:
        row = "  " + d.row()
        if used + len(row.encode("utf-8")) + 1 > left:
            break
        rows.append(row)
        used += len(row.encode("utf-8")) + 1
    more = len(c.items) - len(rows)
    lines = [f"  {len(c.items)} diagnostic{'s' if len(c.items) != 1 else ''} (file:line:col, severity, rule, message):", *rows]
    if more:
        lines.append(f"  ... {more} more not shown: see the log")
    if c.last:
        lines += ["  its last words:", *("  " + x for x in c.last.splitlines())]
    return "\n".join([head, *lines, *([c.note] if c.note else [])])


def render_all(checks: Sequence[CheckDiagnostics], each: int, total: int, tail_lines: int = trim.TAIL) -> str:
    """The failing checks for a prompt: each at most `each` bytes, all at most `total`."""
    out: list[str] = []
    left = total
    for c in checks:
        text = render(c, min(each, left), tail_lines)
        left -= len(text.encode("utf-8")) + 1
        out.append(text)
    return "\n".join(out) or "- (no checks)"
