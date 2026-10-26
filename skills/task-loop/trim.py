"""Trim a check's output before any agent prompt carries it (tl-7y6.7.17). Pure: text in, text out, no I/O.

A red check keeps its failure lines (test names, the first assertion or compile error under each, one line of context)
and the last `tail_lines` lines, within `cap` bytes; the full log stays on disk and its path is the last line.
A green check is one line. Generic: unittest, pytest, dotnet/NUnit/xUnit, compilers, shell exit-only output."""
import re

CAP = 4096
TAIL = 40
LINE_MAX = 240  # a longer line (minified output, a JSON blob) is cut
GAP = "..."
GAP_COST = len(GAP) + 1

# a line that names a failure
FAIL_LINE = re.compile(r"(?i)fail|error|assert|traceback|exception|panic|fatal|\bnot ok\b|\bexpected\b|\bbut was\b|✗|✘|: E\b|^E\s")
# a line that only looks like one: "0 Error(s)", "Failed: 0", "failures=0", analyzer warnings
NOISE_LINE = re.compile(r"(?i)\b0 errors?\b|\b0 error\(s\)|\b0 fail\w*|\bfail\w*[:=] ?0\b|\berrors?[:=] ?0\b|\bwarning [A-Z]+\d+:|\bwarn(?:ing)?:")
# a line that names a failed test or a compile error: kept first
NAME_LINE = re.compile(
    r"^\s*(?:FAIL(?:ED)?\b|ERROR\b|Failed\b|\[FAIL\]|not ok\b|\d+\) )|^_{2,} .+ _{2,}$|^=+ (?:FAILURES|ERRORS) =+|"
    r"\berror [A-Za-z]*\d+|: error\b|^\s*Traceback \(|\bfailed\b.*\[\d+ ?m?s\]|\bFAILED \(")


def _clip(line, n=LINE_MAX):
    line = line.rstrip()
    return line if len(line) <= n else line[:n - 3] + "..."


def _size(line):
    return len(line.encode("utf-8", "replace")) + 1


def trim_log(text, log="", cap=CAP, tail_lines=TAIL):
    """The text of a red check's log cut to at most `cap` bytes: failure lines first, then the last `tail_lines` lines
    (noise dropped, the very last line always), in log order with gap marks, and a final line naming the full log."""
    rows = [_clip(ln) for ln in str(text or "").splitlines()]
    while rows and not rows[-1].strip():
        rows.pop()
    foot = ("(trimmed from %d lines; full log: %s)" % (len(rows), log) if log else "(trimmed from %d lines)" % len(rows))
    if not rows:
        return ""
    if len(rows) <= tail_lines and sum(_size(r) for r in rows) + _size(foot) <= cap:
        return "\n".join(rows + ([foot] if log else []))
    budget = cap - _size(foot)
    keep = set()
    used = 0

    def take(i):
        nonlocal used
        if i in keep or not 0 <= i < len(rows) or not rows[i].strip():
            return True
        cost = _size(rows[i]) + GAP_COST
        if used + cost > budget:
            return False
        keep.add(i)
        used += cost
        return True

    take(len(rows) - 1)  # the last line is always there (a timeout says so on it)
    # the tail gets a third of the room; the failures get the rest and whatever the tail leaves
    spent, tail_idx = 0, []
    for i in range(len(rows) - 2, -1, -1):
        if len(tail_idx) >= tail_lines - 1:
            break
        if not rows[i].strip() or NOISE_LINE.search(rows[i]):
            continue
        spent += _size(rows[i]) + GAP_COST
        if spent > budget // 3:
            break
        tail_idx.append(i)
    names = [i for i, r in enumerate(rows) if NAME_LINE.search(r) and not NOISE_LINE.search(r)]
    hits = [i for i, r in enumerate(rows) if FAIL_LINE.search(r) and not NOISE_LINE.search(r)]
    nameset = set(names)
    firsts = []  # the first non-name hit under each name: its assertion
    for k, n in enumerate(names):
        end = names[k + 1] if k + 1 < len(names) else len(rows)
        nxt = next((h for h in hits if n < h < end and h not in nameset), None)
        if nxt is not None:
            firsts.append(nxt)
    ctx = [j for i in sorted(set(names) | set(firsts)) for j in (i - 1, i + 1)]
    rest = [h for h in hits if h not in nameset and h not in set(firsts)]
    # fair order: every name and its assertion before any second hit, then context, then the rest of the tail
    full = False
    for i in tail_idx:
        take(i)
    for group in (sorted(set(names) | set(firsts)), rest, ctx):
        for i in group:
            if not take(i):
                full = True
                break
        if full:
            # a full budget stops the lower groups, but a name or an assertion still left out is counted below
            break
    out, prev = [], -1
    for i in sorted(keep):
        if i - prev > 1:
            out.append(GAP)
        out.append(rows[i])
        prev = i
    left = [i for i in names if i not in keep]
    if left:
        foot = "(%d more failing lines left out; %s)" % (len(left), foot[1:-1])
    res = "\n".join(out + [foot])
    if _size(res) > cap:  # the gap marks cost what take() reckoned, so this is a backstop only
        res = res.encode("utf-8", "replace")[:cap - 4].decode("utf-8", "ignore") + "\n..."
    return res


def green_line(cmd, secs=None, log=""):
    """A passing check: one line, no output."""
    return "`%s` passed%s%s" % (cmd if len(cmd) <= 200 else cmd[:200] + "...",
                                " in %s s" % int(secs) if isinstance(secs, (int, float)) else "", " (log: %s)" % log if log else "")
