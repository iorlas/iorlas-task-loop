"""Every regular expression the diagnostics parser needs: the output formats of the checks we register, one table each.
A line format (`SINGLE`) reads a whole diagnostic from one line; a two-line format (`HEADS` then ARROW) puts the message on one line
and the place on the next (ruff, pyrefly). The one place in domain/checks/diag that imports `re`."""
import re
from typing import Final, NamedTuple

ANSI: Final = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SEVERITY: Final = re.compile(r"(?i)^(error|warning|warn|info|note|hint)\b:?\s*")
RULE: Final = re.compile(r"^(?:\[?([A-Za-z]{1,8}\d{2,5})\]?:?\s+)(?:\[\*\]\s+)?")
PROJECT_SUFFIX: Final = re.compile(r"\s+\[[^\[\]]+?\.(?:cs|vb|fs)?proj(?:::[^\[\]]*)?\]$")


class Raw(NamedTuple):
    """What one format read from its line(s); the severity and rule are empty when the format has none."""
    path: str
    line: int
    col: int
    severity: str
    rule: str
    message: str


# one line, whole: (name, pattern with the groups path, line, col?, severity?, rule?, msg)
SINGLE: Final = (
    # Roslyn / MSBuild: path(line,col): warning CA1822: message [project.csproj]
    ("roslyn", re.compile(r"^(?P<path>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\):\s*(?P<sev>error|warning|info)\s+"
                          r"(?P<rule>[A-Za-z]+\d+)\s*:\s*(?P<msg>.*)$")),
    # generic compiler / linter: path:line:col: message (col optional; a leading severity and rule word are read out of the message)
    ("generic", re.compile(r"^(?P<path>[^\s:()][^:()]*?\.\w+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<msg>\S.*)$")),
)

# the message line of a two-line format, followed by an ARROW line
HEADS: Final = (
    # ruff (full): `F401 [*] `os` imported but unused`
    ("ruff", re.compile(r"^(?P<rule>[A-Z]{1,5}\d{2,4})\s+(?:\[\*\]\s+)?(?P<msg>\S.*)$")),
    # pyrefly: `ERROR `int` is not assignable to `str` [bad-assignment]`
    ("pyrefly", re.compile(r"^(?P<sev>ERROR|WARN|WARNING|INFO)\s+(?P<msg>.+?)(?:\s+\[(?P<rule>[a-z0-9-]+)\])?$")),
)
ARROW: Final = re.compile(r"^\s*-->\s*(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))?\s*$")


def clean(line: str) -> str:
    return ANSI.sub("", line).rstrip()


def _raw(m: re.Match[str]) -> Raw:
    g = m.groupdict()
    msg = PROJECT_SUFFIX.sub("", g["msg"].strip())
    sev, rule = (g.get("sev") or "").lower(), g.get("rule") or ""
    if not sev and (s := SEVERITY.match(msg)):
        sev, msg = s.group(1).lower(), msg[s.end():]
    if not rule and (r := RULE.match(msg)):
        rule, msg = r.group(1), msg[r.end():]
    return Raw(g.get("path", ""), int(g.get("line") or 0), int(g.get("col") or 0), "warning" if sev == "warn" else sev, rule, msg.strip())


def single(line: str) -> Raw | None:
    """The diagnostic one line holds, by the first format of SINGLE that reads it."""
    for name, pat in SINGLE:
        m = pat.match(line)
        if m:
            raw = _raw(m)
            if name == "generic" and not (raw.severity or raw.rule):  # `tests/a.py:31: AssertionError` is a traceback line, not a finding
                return None
            return raw
    return None


def pair(head: str, arrow: str) -> Raw | None:
    """The diagnostic a message line and the place line under it hold."""
    where = ARROW.match(arrow)
    if not where:
        return None
    for _name, pat in HEADS:
        m = pat.match(head)
        if m:
            g = {**m.groupdict(), **where.groupdict()}
            sev = (g.get("sev") or "").lower()
            return Raw(g["path"], int(g["line"]), int(g.get("col") or 0), "warning" if sev == "warn" else sev, g.get("rule") or "",
                       g["msg"].strip())
    return None
