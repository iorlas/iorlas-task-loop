"""The repo's neutral gate plan: bad output makes every check due; a missing executable is a config error."""
import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tlgate.cache import NO_DIGEST, plan_digest
from tlgate.host import CheckHost
from tlkernel import rundocs, wire
from tlkernel.childenv import check_environment
from tlkernel.config import ConfigError
from tlkernel.gateplan import GatePlan
from tlkernel.runkey import Digest
from tlkernel.slots import SlotGitError

PLAN_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class PlanDecision:
    """A producer's decisions and evidence; empty output means the plan failed closed."""

    skips: dict[str, str]
    command: Digest = NO_DIGEST
    output: Digest = NO_DIGEST


def parse(text: str) -> GatePlan:
    """Strict types and required fields, open to future producer fields and the id/why aliases."""
    plan = wire.load(GatePlan, text)
    names: set[str] = set()
    for step in plan.steps:
        name = step.name if step.name is not None else step.id
        reason = step.reason if step.reason is not None else step.why
        if not name or reason is None:
            raise ValueError("every plan step needs name (or id) and reason (or why)")
        if name in names:
            raise ValueError(f"duplicate plan step: {name}")
        names.add(name)
    return plan


def once(host: CheckHost, reason: str) -> bool:
    """Persist the diagnostic key in the run directory, including across engine reloads."""
    return rundocs.once(host.home, host.run_id, hashlib.sha256(reason.encode()).hexdigest())


def command(host: CheckHost, cmd: list[str]) -> list[str]:
    """Resolve the producer in its execution environment, with Python's portable spelling."""
    path = host.bead_env.get("PATH", host.env.get("PATH"))
    word = cmd[0] if cmd else ""
    if word == "python" and not shutil.which(word, path=path):
        word = "python3" if shutil.which("python3", path=path) else sys.executable
    candidate = str(Path(host.wt) / word) if "/" in word and not Path(word).is_absolute() else word
    if not word or not shutil.which(candidate, path=path):
        reason = f"engine.plan_cmd: executable {word!r} does not resolve on PATH in {host.wt}"
        if once(host, reason):
            host.log.note("config error: " + reason)
        raise ConfigError(reason)
    return [word, *cmd[1:]]


def skipped(host: CheckHost, tree: str, base: str) -> PlanDecision | None:
    """None preserves the legacy `when` decision; a configured but unusable plan skips nothing."""
    cmd = host.cfg.plan_cmd
    if cmd is None:
        return None
    argv = command(host, cmd)
    try:
        if not base or not tree:
            raise ValueError("the tree or resolved base is missing")
        wt = str(host.wt)
        if host.git.dirty(wt):
            raise ValueError("checkout is dirty")
        if host.git.rev_parse(wt, "HEAD^{tree}") != tree:
            raise ValueError("HEAD tree differs from the judged tree")
        # The producer can read the checkout as well as the supplied paths.
        start = host.git.merge_base(wt, base, "HEAD")
        if not start:
            raise ValueError("cannot resolve the diff's merge-base")
        paths = host.git.changed_paths(wt, start, tree, required=True)
        with check_environment(host.env.vars, host.bead_env, scratch_home=host.cfg.check_scratch_home) as env:
            ran = host.spawner.run([*argv, "--base", base, "--paths-stdin"], cwd=wt, env={},
                                   extra=env, timeout_s=PLAN_TIMEOUT_S, input="".join(p + "\0" for p in paths))
        if ran.timed_out:
            raise ValueError(f"command timed out after {PLAN_TIMEOUT_S:g}s")
        if ran.exit:
            raise ValueError(f"command exited {ran.exit}")
        plan = parse(ran.out)
        if plan.base is not None and plan.base != base:
            raise ValueError("plan base differs from the requested base")
        skips = {(s.name if s.name is not None else s.id) or "":
                 (s.reason if s.reason is not None else s.why) or "" for s in plan.steps if not s.run}
        return PlanDecision(skips, plan_digest(cmd), Digest(hashlib.sha1(ran.out.encode("utf-8")).hexdigest()))
    except (OSError, ValueError, SlotGitError) as err:
        reason = " ".join(str(err).splitlines())
        if once(host, reason):
            host.warn("plan not used; every step required: " + reason)
        return PlanDecision({})
