"""Trim a check's output before any agent prompt carries it (tl-7y6.7.17). Pure: text in, text out, no I/O.

A red check keeps its failure lines (test names, the first assertion or compile error under each, one line of context)
and the last `tail_lines` lines, within `cap` bytes; the full log stays on disk and its path is the last line.
A green check is one line. Generic: unittest, pytest, dotnet/NUnit/xUnit, compilers, shell exit-only output."""
from taskloop.domain.checks.matchers import is_failure, is_name, is_noise

CAP = 4096
TAIL = 40
LINE_MAX = 240  # a longer line (minified output, a JSON blob) is cut
GAP = "..."
GAP_COST = len(GAP) + 1


def _clip(line: str, n: int = LINE_MAX) -> str:
    line = line.rstrip()
    return line if len(line) <= n else line[:n - 3] + "..."


def _size(line: str) -> int:
    return len(line.encode("utf-8", "replace")) + 1


def _deduped(rows: list[str]) -> list[str]:
    """A failure line the log repeats word for word is said once."""
    said: set[str] = set()
    short: list[str] = []
    for r in rows:
        if is_failure(r) and r in said:
            continue
        said.add(r)
        short.append(r)
    return short


class _Keep:
    """The lines chosen so far, within a byte budget; a line the log repeats word for word is chosen once when asked to."""

    def __init__(self, rows: list[str], budget: int) -> None:
        self.rows, self.budget = rows, budget
        self.keep: set[int] = set()
        self.seen: set[str] = set()
        self.used = 0

    def take(self, i: int, once: bool = False) -> bool:
        rows = self.rows
        if i in self.keep or not 0 <= i < len(rows) or not rows[i].strip() or (once and rows[i] in self.seen):
            return True
        cost = _size(rows[i]) + GAP_COST
        if self.used + cost > self.budget:
            return False
        self.keep.add(i)
        self.seen.add(rows[i])
        self.used += cost
        return True


def _tail_lines(rows: list[str], budget: int, tail_lines: int) -> list[int]:
    """The tail gets a third of the room: the last lines that say something, newest first."""
    spent = 0
    out: list[int] = []
    for i in range(len(rows) - 2, -1, -1):
        if len(out) >= tail_lines - 1:
            break
        if not rows[i].strip() or is_noise(rows[i]):
            continue
        spent += _size(rows[i]) + GAP_COST
        if spent > budget // 3:
            break
        out.append(i)
    return out


def _failure_groups(rows: list[str]) -> tuple[list[int], list[int], list[int], list[int]]:
    """(names, the first assertion under each name, the other failure lines, the lines around a name or an assertion)."""
    names = [i for i, r in enumerate(rows) if is_name(r) and not is_noise(r)]
    hits = [i for i, r in enumerate(rows) if is_failure(r) and not is_noise(r)]
    nameset = set(names)
    firsts = []
    for k, n in enumerate(names):
        end = names[k + 1] if k + 1 < len(names) else len(rows)
        nxt = next((h for h in hits if n < h < end and h not in nameset), None)
        if nxt is not None:
            firsts.append(nxt)
    ctx = [j for i in sorted(nameset | set(firsts)) for j in (i - 1, i + 1)]
    rest = [h for h in hits if h not in nameset and h not in set(firsts)]
    return names, firsts, rest, ctx


def _fill(keep: _Keep, tail_idx: list[int], groups: tuple[list[int], ...]) -> None:
    """Fair order: the tail, then every name and its assertion before any second hit, then context; a full budget stops the lower groups."""
    for i in tail_idx:
        keep.take(i, once=True)
    for group in groups:
        if not all(keep.take(i, once=True) for i in group):
            return


def trim_log(text: object, log: str = "", cap: int = CAP, tail_lines: int = TAIL) -> str:
    """The text of a red check's log cut to at most `cap` bytes: failure lines first, then the last `tail_lines` lines
    (noise dropped, the very last line always), in log order with gap marks, and a final line naming the full log."""
    rows = [_clip(ln) for ln in str(text or "").splitlines()]
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        return ""
    foot = f"(trimmed from {len(rows)} lines; full log: {log})" if log else f"(trimmed from {len(rows)} lines)"
    if len(rows) <= tail_lines and sum(_size(r) for r in rows) + _size(foot) <= cap:
        return "\n".join(_deduped(rows) + ([foot] if log else []))
    keep = _Keep(rows, cap - _size(foot))
    keep.take(len(rows) - 1)  # the last line is always there (a timeout says so on it)
    names, firsts, rest, ctx = _failure_groups(rows)
    _fill(keep, _tail_lines(rows, keep.budget, tail_lines), (sorted(set(names) | set(firsts)), rest, ctx))
    out: list[str] = []
    prev = -1
    for i in sorted(keep.keep):
        if i - prev > 1:
            out.append(GAP)
        out.append(rows[i])
        prev = i
    left = [i for i in names if i not in keep.keep]
    if left:
        foot = f"({len(left)} more failing lines left out; {foot[1:-1]})"
    res = "\n".join([*out, foot])
    if _size(res) > cap:  # the gap marks cost what take() reckoned, so this is a backstop only
        res = res.encode("utf-8", "replace")[:cap - 4].decode("utf-8", "ignore") + "\n..."
    return res


def green_line(cmd: str, secs: float | None = None, log: str = "") -> str:
    """A passing check: one line, no output."""
    return "`{}` passed{}{}".format(cmd if len(cmd) <= 200 else cmd[:200] + "...",
                                f" in {int(secs)} s" if isinstance(secs, (int, float)) else "", f" (log: {log})" if log else "")
