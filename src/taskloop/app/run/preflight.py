"""Read-only admission and plans, before an engine opens files or takes a bead."""
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.checks.runner import cached_gate
from taskloop.app.run.bead_env import bead_env
from taskloop.app.run.console import say
from taskloop.app.run.layout import repo_of
from taskloop.app.run.stages import select_step
from taskloop.app.run.state import read_checkpoint
from taskloop.app.wire.closeguard import has_land
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Step
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, TreeSha
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git
from taskloop.stores.real import real_stores


@dataclass
class Preview:
    git: Git
    wt: str
    home: ConfigDir
    cfg: EngineConfig


def _inspect_uncommitted(wt: str, paths: list[str], last: RunBundle | None, *, force: bool, continuous: bool) -> None:
    if paths and not continuous:
        state = str(last.manifest.state) if last else "unrecorded"
        say(f"uncommitted work in {wt} (previous run: {state}); a WIP commit would include {len(paths)} files:")
        for path in paths:
            say(f"  {path}")
        if not force:
            raise ValueError("uncommitted work refused: use --force to allow a WIP commit")


def inspect(bead: BeadId, wt: str, repo: str, cfg: EngineConfig, *, git: Git, who: Identity, env: Env,
            requested: str | None, fresh: bool, force: bool, continuous: bool, dry: bool, slot: str = "") -> str:
    """Return the refusal, if any. No claims, layouts, manifests, plan commands or index writes."""
    if not dry and (continuous or not requested):
        return ""
    stores = real_stores(who.config)
    locator = RunLocator(who.config)
    last = locator.newest(bead, repo_of(git, wt) if wt else repo)
    ck = None if fresh else read_checkpoint(stores, bead)
    branch = git.branch(wt) if wt else ""
    top = git.toplevel(wt) if branch == f"task/{bead}" else ""
    checkout = bool(top) and Path(top).resolve() == Path(wt).resolve()
    if dry:
        say(f"plan: bead {bead}; stage {requested or ('loop' if continuous else 'auto-next')}")
        say(f"worktree: {wt or '(new worktree)'}; slot: {slot or '(none)'}; lease: would acquire")
        say(f"branch: {branch or '(new task branch)'}")
    try:
        step = select_step(last, ck, fresh, requested)
        if dry:
            say(f"next stage: {step}")
        paths = (sorted({row.path for row in git.status(wt, all_untracked=True)})
                 if not continuous and checkout else [])
        _inspect_uncommitted(wt, paths, last, force=force, continuous=continuous)
        if dry and not continuous:
            if step is Step.CLOSE and not has_land(who, bead):
                raise ValueError("close refused: no land on record; run --stage land")
            if step is Step.LAND:
                tree = TreeSha(git.rev_parse(wt, "HEAD^{tree}")) if checkout and not paths else TreeSha("")
                view = Preview(git, wt, who.config, cfg)
                # A preview never executes plan_cmd. Without its answer every gate step is required.
                planned: dict[str, str] | None = {} if cfg.plan_cmd is not None else None
                if planned is not None:
                    say("gate plan: producer deferred; requiring cached passes for every gate step")
                if not cached_gate(cfg, git, wt, stores, env, bead_env(view, create=False), tree, planned):
                    raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
        if dry:
            say("refusals: none")
    except ValueError as err:
        return str(err)
    return ""
