"""WriterSplit: which checks the writer may run itself and which are the engine's alone. Pure."""
from collections.abc import Mapping, Sequence

from taskloop.contracts.checks import Check
from taskloop.contracts.config import EngineConfig
from taskloop.domain.checks.matchers import canon, looks_slow
from taskloop.domain.checks.names import norm
from taskloop.domain.checks.shell import matchers as sh
from taskloop.domain.checks.specs import repo_check


class WriterSplit:
    """A check is the engine's when its longest passing run took more than `engine.writer_check_max_s`, or it never ran and its name
    says Unity, play, full test, check or build; the gate always is. A repo check overrides that: `writer: true` (or false), or its
    own `writer_check_max_s`."""

    def __init__(self, cfg: EngineConfig, secs: Mapping[str, float]) -> None:
        self.cfg, self.secs = cfg, secs
        self.repo = [repo_check(k, cfg) for k in cfg.checks]

    def _spec(self, cmd: str) -> Check | None:
        want = canon(cmd)
        return next((k for k in self.repo if canon(k.cmd) == want), None)

    def engine_only(self, cmd: str) -> bool:
        if cmd == self.cfg.gate:
            return True
        spec = self._spec(cmd)
        if spec is not None and spec.writer is not None:
            return not spec.writer
        s = self.secs.get(norm(cmd), self.secs.get(cmd))
        cut = spec.writer_max_s if spec is not None and spec.writer_max_s is not None else float(self.cfg.writer_check_max_s)
        return s > cut if s is not None else looks_slow(cmd)

    def engine_recipes(self) -> list[str]:
        """The bare `just` recipe names of the configured checks (and the gate) a writer must not run: delegate's guard blocks them
        (`route.py run --engine-only`). Only a check that is exactly `just <recipe>` has a recipe name."""
        out: list[str] = []
        for cmd in [self.cfg.gate, *(k.cmd for k in self.repo)]:
            toks = sh.shell_tokens(cmd) if cmd else []
            if len(toks) == 2 and toks[0] == "just" and toks[1] not in out and self.engine_only(cmd):
                out.append(toks[1])
        return out

    def divide(self, cmds: Sequence[str]) -> tuple[list[str], list[str]]:
        """(the writer's, the engine's) among the commands."""
        slow = [c for c in cmds if self.engine_only(c)]
        return [c for c in cmds if c not in slow], slow

    def text(self, checks: Sequence[str], skip: Sequence[str] | None = None) -> str:
        """The stage's check list split for the writer: the fast ones it may run, the slow ones the engine runs alone. `skip`: the
        commands the last engine run found red: where() lists those, so each command is named once."""
        checks = list(dict.fromkeys(checks))
        if not checks:
            return "- (none named)"
        if skip is not None:
            gone = {norm(c) for c in skip}
            checks = [c for c in checks if norm(c) not in gone]
            if not checks:
                return "- (the failed ones are listed below)"
        fast, slow = self.divide(checks)
        text = ""
        if fast:
            text += "You may run these:\n" + "\n".join("- " + c for c in fast)
        if slow:
            text += ("\n" if text else "") + "The engine runs these, do not run them:\n" + "\n".join("- " + c for c in slow)
        return text
