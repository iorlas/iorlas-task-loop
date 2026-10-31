"""The one reader of a repo's neutral gate plan; a failed producer makes every check due."""
from taskloop.app.checks.host import CheckHost
from taskloop.contracts import wire
from taskloop.contracts.gateplan import GatePlan
from taskloop.contracts.slots import SlotGitError

PLAN_TIMEOUT_S = 30.0


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


def skipped(host: CheckHost, tree: str, base: str) -> dict[str, str] | None:
    """None preserves the legacy `when` decision; a configured but unusable plan skips nothing."""
    cmd = host.cfg.plan_cmd
    if cmd is None:
        return None
    try:
        if not base or not tree:
            raise ValueError("the tree or resolved base is missing")
        wt = str(host.wt)
        # tree_hash includes uncommitted paths. Diff its tree against the merge-base:
        # for a clean checkout this is exactly base...HEAD, without losing dirty paths.
        start = host.git.merge_base(wt, base, "HEAD")
        if not start:
            raise ValueError("cannot resolve the diff's merge-base")
        paths = host.git.changed_paths(wt, start, tree)
        if not paths and host.git.rev_parse(wt, f"{start}^{{tree}}") != tree:
            raise ValueError("cannot read the changed paths")  # the port answers [] on a git failure: an empty diff must be a real one
        ran = host.spawner.run([*cmd, "--base", base, "--paths-stdin"], cwd=wt,
                               extra=host.bead_env, timeout_s=PLAN_TIMEOUT_S,
                               input="".join(p + "\0" for p in paths))
        if ran.timed_out:
            raise ValueError(f"command timed out after {PLAN_TIMEOUT_S:g}s")
        if ran.exit:
            raise ValueError(f"command exited {ran.exit}")
        plan = parse(ran.out)
        return {(s.name if s.name is not None else s.id) or "":
                (s.reason if s.reason is not None else s.why) or "" for s in plan.steps if not s.run}
    except (OSError, ValueError, SlotGitError) as err:
        host.warn("plan not used; every step required: " + " ".join(str(err).splitlines()))
        return {}
