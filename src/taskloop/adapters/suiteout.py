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


def ran_line(out: str) -> str:
    """pytest's closing line ("2041 passed, 19 skipped in 55.19s"; with or without its "=" frame), else "no summary"."""
    last = re.findall(r"^(?:=+ )?(\d+ \w+.* in [\d.]+s(?: \([\d:]+\))?)(?: =+)?$", out, re.M)
    return last[-1] if last else "no summary"


def merge_outputs(parts: list[Part]) -> tuple[str, bool]:
    """The runs' text one after the other, each under its name; green only when every run exited 0."""
    text = "\n".join(f"== {p.name} (exit {p.code}) ==\n{p.out.strip()}" for p in parts)
    return text + "\n", all(p.code == 0 for p in parts)
