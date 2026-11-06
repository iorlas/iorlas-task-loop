"""The text pytest prints: what a red suite shows, and the runs' outputs merged into one."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Part:
    name: str
    code: int
    out: str


def failure_report(out: str) -> str:
    """The ERRORS and FAILURES sections of pytest output with their tracebacks, the "short test summary info" and the closing line;
    not the passing dots, nor the warnings summary."""
    keep: list[str] = []
    on = skipping = False
    for line in out.splitlines():
        header = line.startswith("=")
        if header and re.match(r"=+ (ERRORS|FAILURES) =+$", line):
            on = True
        if header:
            skipping = "warnings summary" in line
        if on and not skipping:
            keep.append(line)
    return "\n".join(keep)


def failing_tests(out: str) -> list[str]:
    """The node ids pytest's short summary lists as failed or errored."""
    return re.findall(r"^(?:FAILED|ERROR|SUBFAILED\S*) (\S+)", out, re.M)

