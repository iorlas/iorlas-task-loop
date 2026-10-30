"""AcProbe (tl-9un.1): what the bead's acceptance names that cannot work, found before the planner runs. Nothing copied from bead text
is ever executed (SAFEACT): a command that is a check of the repo's profile (by id, or by its exact argv) runs once on the base through
the check runner, with its cache and limits; any other command is only looked up (its program on the PATH a check sees, or a path
in the repo). What comes back is a planner fact: a missing program, a check that already passes, a check this host cannot run."""
from pathlib import Path
from typing import Protocol

from taskloop.adapters.check_probe import PathProbe
from taskloop.app.checks.runner import Checker
from taskloop.contracts.checks import UNVERIFIED_EXIT, CheckResult
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.domain.beads import matchers as acnames
from taskloop.domain.checks.specs import repo_check
from taskloop.domain.matchers import clip
from taskloop.stores.runlog import RunLog

MAX_RUNS = 3  # registered checks one probe runs
NOT_RUNNABLE = (UNVERIFIED_EXIT, 126, 127)  # could not verify, not executable, not found: the host, not the code


class ProbeHost(Protocol):
    """The Engine, as the probe sees it."""

    cfg: EngineConfig
    scope: str
    log: RunLog
    checker: Checker

    def now(self) -> float: ...
    def shell_probe(self) -> PathProbe: ...


class AcProbe:
    def __init__(self, host: ProbeHost) -> None:
        self.e = host
        self.facts: list[str] | None = None

    def text(self) -> str:
        """The planner's block of facts, probed once per run ('' when there are none)."""
        if self.facts is None:
            self.facts = self.probe()
        if not self.facts:
            return ""
        return ("\n\nWhat the engine found in the acceptance before you plan (nothing from the bead's text was run; registered checks "
                "ran once on the base):\n" + "".join(f"- {f}\n" for f in self.facts))

    def probe(self) -> list[str]:
        e = self.e
        started = e.now()
        registry = [(str(k.id), list(k.argv)) for k in e.cfg.checks]
        named = acnames.commands(e.scope or "", {cid for cid, _ in registry})
        facts: list[str] = []
        runs = 0
        for c in named:
            cid = acnames.registered(c, registry)
            if cid is None:
                if why := self.missing(c):
                    facts.append(why)
                continue
            spec = next(k for k in e.cfg.stage_checks if k.id == cid) if any(k.id == cid for k in e.cfg.stage_checks) else None
            if spec is None or runs >= MAX_RUNS:
                e.log.note(f"acceptance probe: `{cid}` not run ({'it runs only in the land gate' if spec is None else 'probe limit'})")
                continue
            runs += 1
            if fact := self.run_one(spec):
                facts.append(fact)
        e.log.note(f"acceptance probe: {len(named)} command(s) named, {runs} registered check(s) run, {len(facts)} fact(s) "
                   f"in {e.now() - started:.1f} s")
        return facts

    def missing(self, c: acnames.Named) -> str:
        """A command not in the profile: its program is looked up, never run."""
        e = self.e
        argv = [w for w in c.argv if not ("=" in w and w.split("=", 1)[0].isidentifier())]
        argv = argv[1:] if argv[:1] == ["env"] else argv
        if not argv:
            return ""
        head = argv[0]
        probe = e.shell_probe()
        found = (Path(head).exists() if head.startswith("/") else probe.exists(head)) if "/" in head else probe.has_command(head)
        e.log.note(f"acceptance probe: `{head}` {'found' if found else 'not found'} (looked up, not run)")
        return "" if found else f"AC names `{c.text}`, which does not exist here (`{head}` is not on the PATH of the checks)"

    def run_one(self, spec: CheckSpec) -> str:
        e = self.e
        n = e.checker.round
        try:
            run = e.checker.run_items([repo_check(spec, e.cfg)], everything=True, learn=False)
        finally:
            e.checker.round = n  # the probe is no round: the stage rounds keep their numbers
        got: CheckResult | None = next((r for r in run.results if r.id == spec.id), None)
        if got is None:
            return ""
        e.log.note(f"acceptance probe: `{spec.id}` {got.word.value} (exit {got.exit}) in {got.secs:.1f} s on the base")
        if got.status == "passed":
            return f"AC names the check `{spec.id}`, which is already true: it passes on the base; plan nothing to make it pass"
        if got.exit in NOT_RUNNABLE:
            return (f"AC names the check `{spec.id}`, which cannot run on this host ({got.status}, exit {got.exit}): "
                    f"{clip(got.tail, 200)}. If the work depends on it, ask the owner now; do not plan rounds against it")
        return ""
