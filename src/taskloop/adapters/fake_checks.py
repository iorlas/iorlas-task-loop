"""`FakeChecks`: scripted pass or fail per command, no shell. A command with no script passes."""
from dataclasses import dataclass, field

from taskloop.contracts.ports import CheckResult, CheckSpec


def passed(out: str = "") -> CheckResult:
    return CheckResult(exit=0, out=out)


def failed(out: str = "", exit: int = 1) -> CheckResult:
    return CheckResult(exit=exit, out=out)


def hung(out: str = "") -> CheckResult:
    return CheckResult(exit=124, out=out, timed_out=True)


@dataclass
class FakeChecks:
    default: CheckResult = field(default_factory=passed)
    scripts: dict[str, list[CheckResult]] = field(default_factory=dict)
    ran: list[CheckSpec] = field(default_factory=list)

    def when(self, cmd: str, *results: CheckResult) -> FakeChecks:
        """The next runs of exactly `cmd` answer `results` in order; the last one repeats."""
        self.scripts[cmd] = list(results)
        return self

    def run(self, spec: CheckSpec) -> CheckResult:
        self.ran.append(spec)
        queue = self.scripts.get(spec.cmd)
        if not queue:
            return self.default
        return queue.pop(0) if len(queue) > 1 else queue[0]
