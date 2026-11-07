"""Read-only admission and plans, before an engine opens files or takes a bead."""

from tlgate import gateplan
from tlgate.runner import cached_gate
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlpipeline.api import admission, read_checkpoint

from taskloop.app.run.layout import repo_of
from taskloop.app.track import console
from taskloop.app.wire.closeguard import has_land
from taskloop.stores.real import real_stores


def inspect(bead: BeadId, wt: str, repo: str, cfg: EngineConfig, *, git: Git, who: Identity, env: Env,
            requested: str | None, fresh: bool, force: bool, continuous: bool, dry: bool, slot: str = "") -> str:
    """Return the refusal, if any. No claims, layouts, manifests, plan commands or index writes."""
    stores = real_stores(who.config)
    locator = RunLocator(who.config)
    return admission.inspect(bead, wt, repo, git=git, printer=console,
        newest=lambda bead, repo: locator.newest(bead, repo_of(git, wt) if wt else repo),
        checkpoint=lambda: read_checkpoint(stores, bead), has_land=lambda: has_land(who, bead),
        green_gate=lambda tree, planned: cached_gate(cfg, git, wt, stores, env, tree,
            gateplan.PlanDecision({}) if planned else None, clean=True), plan_deferred=cfg.plan_cmd is not None,
        requested=requested, fresh=fresh, force=force, continuous=continuous, dry=dry, slot=slot)
