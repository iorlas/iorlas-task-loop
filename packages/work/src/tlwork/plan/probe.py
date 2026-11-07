"""AcProbe (tl-9un.1): what the bead's acceptance names that cannot work, found before the planner runs. Nothing copied from bead text
is ever executed (SAFEACT): a command that is a check of the repo's profile (by id, or by its exact argv) runs once on the base through
the check runner, with its cache and limits; any other command is only looked up (its program on the PATH a check sees, or a path
in the repo). What comes back is a planner fact: a missing program, a check that already passes, a check this host cannot run."""
from pathlib import Path

from tlgate.api import repo_check
from tlkernel import beadmatchers as acnames
from tlkernel.checks import UNVERIFIED_EXIT, CheckResult
from tlkernel.config import CheckSpec
from tlkernel.matchers import clip
from tlkernel.stagefacts import RunFacts

from tlwork.plan.amend import AmendState
from tlwork.plan.host import PlanHand, PlanPorts
from tlwork.plan.state import PlanState

MAX_RUNS = 3  # registered checks one probe runs
NOT_RUNNABLE = (UNVERIFIED_EXIT, 126, 127)  # could not verify, not executable, not found: the host, not the code


class AcProbe:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand
        self.probed: list[str] | None = None

    def text(self) -> str:
        """The planner's block of facts, probed once per run ('' when there are none)."""
        if self.probed is None:
            self.probed = self.probe()
        if not self.probed:
            return ""
        return ("\n\nWhat the engine found in the acceptance before you plan (nothing from the bead's text was run; registered checks "
                "ran once on the base):\n" + "".join(f"- {f}\n" for f in self.probed))

    def probe(self) -> list[str]:
        started = self.ports.now()
        registry = [(str(k.id), list(k.argv)) for k in self.facts.cfg.checks]
        named = acnames.commands(self.hand.scope or "", {cid for cid, _ in registry})
        facts: list[str] = []
        runs = 0
        for c in named:
            cid = acnames.registered(c, registry)
            if cid is None:
                if why := self.missing(c):
                    facts.append(why)
                continue
            spec = (next(k for k in self.facts.cfg.stage_checks if k.id == cid)
                    if any(k.id == cid for k in self.facts.cfg.stage_checks) else None)
            if spec is None or runs >= MAX_RUNS:
                why = "it runs only in the land gate" if spec is None else "probe limit"
                self.ports.log.note(f"acceptance probe: `{cid}` not run ({why})")
                continue
            runs += 1
            if fact := self.run_one(spec):
                facts.append(fact)
        self.ports.log.note(f"acceptance probe: {len(named)} command(s) named, {runs} registered check(s) run, {len(facts)} fact(s) "
                   f"in {self.ports.now() - started:.1f} s")
        return facts

    def missing(self, c: acnames.Named) -> str:
        """A command not in the profile: its program is looked up, never run."""
        argv = [w for w in c.argv if not ("=" in w and w.split("=", 1)[0].isidentifier())]
        argv = argv[1:] if argv[:1] == ["env"] else argv
        if not argv:
            return ""
        head = argv[0]
        probe = self.ports.shell_probe()
        found = (Path(head).exists() if head.startswith("/") else probe.exists(head)) if "/" in head else probe.has_command(head)
        self.ports.log.note(f"acceptance probe: `{head}` {'found' if found else 'not found'} (looked up, not run)")
        return "" if found else f"AC names `{c.text}`, which does not exist here (`{head}` is not on the PATH of the checks)"

    def run_one(self, spec: CheckSpec) -> str:
        n = self.ports.checker.round
        try:
            run = self.ports.checker.run_items([repo_check(spec, self.facts.cfg)], everything=True, learn=False)
        finally:
            self.ports.checker.round = n  # the probe is no round: the stage rounds keep their numbers
        got: CheckResult | None = next((r for r in run.results if r.id == spec.id), None)
        if got is None:
            return ""
        self.ports.log.note(f"acceptance probe: `{spec.id}` {got.word.value} (exit {got.exit}) in {got.secs:.1f} s on the base")
        if got.status == "passed":
            return f"AC names the check `{spec.id}`, which is already true: it passes on the base; plan nothing to make it pass"
        if got.exit in NOT_RUNNABLE:
            return (f"AC names the check `{spec.id}`, which cannot run on this host ({got.status}, exit {got.exit}): "
                    f"{clip(got.tail, 200)}. If the work depends on it, ask the owner now; do not plan rounds against it")
        return ""
