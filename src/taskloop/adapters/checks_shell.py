"""`Checks` over a shell: by default bash with -e and pipefail, so a red command in a `;` list or a pipe fails it.
`shell` replaces that argv prefix (tests pass a python interpreter and need no bash)."""
import os
import shutil
from collections.abc import Sequence

from taskloop.adapters.procs import capture as run_group
from taskloop.contracts.ports import CheckResult, CheckSpec

TIMEOUT_NOTE = "\n(timed out after %g min: everything the check started was stopped)"


class ShellChecks:
    def __init__(self, shell: Sequence[str] = ()) -> None:
        self.shell = list(shell) or [shutil.which("bash") or "/bin/bash", "-e", "-o", "pipefail", "-c"]

    def run(self, spec: CheckSpec) -> CheckResult:
        ran = run_group([*self.shell, spec.cmd], spec.cwd, dict(os.environ, **spec.env), spec.timeout_s)
        out = ran.out + ran.err
        if ran.timed_out:
            out += TIMEOUT_NOTE % round(spec.timeout_s / 60, 2)
        return CheckResult(exit=ran.exit, out=out, secs=ran.secs, timed_out=ran.timed_out)
