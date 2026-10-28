"""What a worker is told of its checks: which it may run, which are the engine's, which were red on the untouched base too."""
from typing import Any

from taskloop.domain.checks.names import norm as norm_cmd


class Briefing:
    def __init__(self, host: Any) -> None:
        self.e = host

    def where(self, node: Any, checks: Any = (), failed: Any = None, listed: Any = ()):
        """What the step is for, never what its sandbox allows: delegate tells each worker that (worker-run v3).
        For the writer: which checks it may run (fast ones) and which are the engine's (slow ones), minus `listed` (the
        commands the stage's own check list already names)."""
        e = self.e
        if node == "write":
            pool = list(dict.fromkeys(checks)) if failed is None else list(dict.fromkeys(failed))
            if failed is None:  # the stage's own checks are in stage_checks_text: name each command once (tl-7y6.6.12)
                have = {norm_cmd(c) for c in listed}
                pool = [c for c in pool if norm_cmd(c) not in have]
            fast, slow = e.checker.split().divide(pool)
            if failed is None:
                text = ("Before you say it is done, run the stage's fast checks so an error never reaches the engine; the "
                        "engine reruns every check after you.")
            else:
                text = "Only the failed checks that are fast are yours to rerun; the engine reruns every check after you."
            if slow:
                text += ("\nThe engine runs these after you; do not run them:\n" if failed is None else
                         "\nThese failed checks are slow: the engine re-runs them; fix from the output above, do not run them:\n"
                         ) + "".join(f"- {c}\n" for c in slow).rstrip("\n")
            if fast:
                text += "\nYou may run these:\n" + "\n".join(f"- {c}" for c in fast)
            return (text + "\nIf a command is refused, do not reword it to get around the refusal: say which command and "
                    "why you needed it.\nNever start a command you expect to take over a minute; never poll a running "
                    "command more than 3 times.")
        return "You may run commands to check facts (read files, run a linter or a test); never edit, create or delete files."

    def base_red_text(self, run: Any):
        """What the writer is told of the checks that were red on the untouched base too: they are not its to fix."""
        if not run.base_red:
            return ""
        rows = "\n".join(f"- `{c.cmd}` (exit {c.exit})" for c in run.base_red)
        return f"\nThese checks are red on the untouched base too, so they are not yours; the round does not count them:\n{rows}\n"

    def stage_checks_text(self, checks: Any, skip: Any = None):
        """The stage's check list split for the writer: the fast ones it may run, the slow ones the engine runs alone (WriterSplit)."""
        e = self.e
        return e.checker.split().text(checks, skip)
