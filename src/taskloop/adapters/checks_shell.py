"""`Checks` over a shell: the command goes through bash with -e and pipefail, so a red command in a `;` list or a pipe fails it."""
import os
import shutil

from taskloop.adapters.proc import run_group
from taskloop.contracts.ports import CheckResult, CheckSpec

TIMEOUT_NOTE = "\n(timed out after %g min: everything the check started was stopped)"


class ShellChecks:
    def __init__(self, bash: str = "") -> None:
        self.bash = bash or shutil.which("bash") or "/bin/bash"

    def run(self, spec: CheckSpec) -> CheckResult:
        argv = [self.bash, "-e", "-o", "pipefail", "-c", spec.cmd]
        ran = run_group(argv, spec.cwd, dict(os.environ, **spec.env), spec.timeout_s)
        out = ran.out + ran.err
        if ran.timed_out:
            out += TIMEOUT_NOTE % round(spec.timeout_s / 60, 2)
        return CheckResult(exit=ran.exit, out=out, secs=ran.secs, timed_out=ran.timed_out)
