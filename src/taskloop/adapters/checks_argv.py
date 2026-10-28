"""`Checks` over an argv: the command is exec'd as given, in its own process group, with no shell in between."""
import os

from taskloop.adapters.procs import capture as run_group
from taskloop.contracts.ports import CheckResult, CheckSpec

TIMEOUT_NOTE = "\n(timed out after %g min: everything the check started was stopped)"


class ArgvChecks:
    def run(self, spec: CheckSpec) -> CheckResult:
        ran = run_group(list(spec.argv), spec.cwd, dict(os.environ, **spec.env), spec.timeout_s)
        out = ran.out + ran.err
        if ran.timed_out:
            out += TIMEOUT_NOTE % round(spec.timeout_s / 60, 2)
        return CheckResult(exit=ran.exit, out=out, secs=ran.secs, timed_out=ran.timed_out)
