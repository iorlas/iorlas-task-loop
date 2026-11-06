"""`Checks` over an argv: the command is exec'd as given, in its own process group, with no shell in between."""

from taskloop.adapters.childenv import check_environment
from taskloop.adapters.procs import capture as run_group
from taskloop.contracts.checksport import CheckResult, CheckSpec
from taskloop.contracts.env import Env

TIMEOUT_NOTE = "\n(timed out after %g min: everything the check started was stopped)"


class ArgvChecks:
    def __init__(self, env: Env, *, scratch_home: bool = False) -> None:
        self.env = env
        self.scratch_home = scratch_home

    def run(self, spec: CheckSpec) -> CheckResult:
        with check_environment(self.env.vars, spec.env, scratch_home=self.scratch_home) as env:
            ran = run_group(list(spec.argv), spec.cwd, env, spec.timeout_s)
        out = ran.out + ran.err
        if ran.timed_out:
            out += TIMEOUT_NOTE % round(spec.timeout_s / 60, 2)
        return CheckResult(exit=ran.exit, out=out, secs=ran.secs, timed_out=ran.timed_out)
