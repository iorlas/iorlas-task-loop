"""`tl doctor`: what is off in the repo's setup for the loop, one line each, and the repo-profile report."""
import contextlib
import os
import sys
import time
from pathlib import Path

import tlkernel as contracts
from tlkernel import runlife
from tlkernel.beadsport import BdFailure, BeadQuery
from tlkernel.delegateport import Resolved
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner
from tlkernel.rowstores import ReposStore

from taskloop.adapters import layout_migrate
from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.app.doctor import env_checks, install, ops, profiles, queue, rails
from taskloop.app.doctor.setup_checks import (
    bead_lint_warnings,
    git_warnings,
    launcher_problems,
    layout_warnings,
    legacy_line,
    path_link_line,
)
from taskloop.app.release import catalog, manifest
from taskloop.app.report.inputs import repo_traces
from taskloop.app.slots import watchdog
from taskloop.app.wire import slots as wslots
from taskloop.app.wire.slots import cfg_source
from taskloop.domain.lanes import pin
from taskloop.stores.delegate import real_route
from taskloop.stores.real import real_stores

OWNERSHIP = "## Ownership"


def slot_warnings(repo: str, who: Identity, git: Git, now: float, spawner: Spawner | None = None) -> tuple[str, list[str]]:
    """(the slot table's one-line summary, its WARN lines): the slots as `tl status` and the dash list them, against config and folders."""
    try:
        table = wslots.slot_table(repo, who, git, now)
    except (SystemExit, OSError, ValueError, BdFailure) as err:
        return f"slots: not read ({err})", []
    states = ", ".join(f"{v.id} {v.state}" for v in table.slots) or "none"
    where = f"{table.source} {table.source_sha[:7]}".strip()
    warns = [f"slot {v.id} is {v.state}: {v.idle_why}" for v in table.slots if v.state == "dead"]
    warns += [f"slot {v.id} is above slots.count {table.configured} and still {v.state}" for v in table.slots
              if v.beyond_count and v.state not in ("free", "retiring")]
    if spawner is not None:  # tl-bxk.10.33.12: the liveness invariants, read only (the loop and the waiters heal)
        with contextlib.suppress(SystemExit, OSError, ValueError, BdFailure):
            warns += watchdog.lines(watchdog.look(wslots.slot_env(repo, spawner=spawner, git=git, who=who)))
    return f"slots: {table.configured} configured from {where}; {states}", warns


def install_problems(plugin_root: Path, env: Env) -> list[str]:
    """What is wrong with the plugin install this tl runs from and the one Claude Code records as installed: a file that differs from
    MANIFEST.sha256 (named), an AGENTS.md without its ownership section. A source checkout has no manifest and is checked for none."""
    out = launcher_problems(plugin_root, env)
    try:
        agents = (plugin_root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        agents = ""
    if OWNERSHIP not in agents.splitlines():
        out.append(f"{plugin_root / 'AGENTS.md'} has no '{OWNERSHIP}' section (who may write the checkout, the cache, the ports)")
    claude = claude_dir(env)
    version = catalog.installed_version(claude)
    installed = catalog.cache_dirs(claude).get(version)
    if installed:
        out += [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)]
    return out


def run(plugin_root: Path, env: Env, git: Git, who: Identity, spawner: Spawner | None = None) -> int:
    repo = git.toplevel(".") or os.getcwd()
    if profiles.report(git, repo, ReposStore(ConfigDir(config_dir(env)))):  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = cfg_source(repo, git)
    _, base, commit = source
    print(f"config: .task-loop.json from base {base} at commit {commit}" if commit else
          f"config: .task-loop.json from working tree {repo} (base {base} unresolved; no commit read)")
    slot_line, slot_warns = slot_warnings(repo, who, git, time.time(), spawner)
    print(slot_line)
    link_line, foreign = path_link_line(env)
    if not foreign:
        print(link_line)  # a foreign `tl` is a WARN below
    warns = git_warnings(repo, source, git) + layout_warnings(repo, source, git) + bead_lint_warnings(repo, who) + slot_warns
    warns += [link_line] if foreign else []
    warns += [] if source[0].engine.writer_exec_allow else [
        "plan check argv unrestricted: the profile lists no engine.writer_exec_allow, so a planner's own check may run any command"]
    warns += ops.clone_warnings(config_dir(env), git)
    lib = real_route().resolve()
    warns += [gap] if (gap := ops.capability_gap(lib.contract if isinstance(lib, Resolved) else {})) else []
    warns += [f"run {r} is lost: its process is gone and it recorded no end" for r in runlife.reconcile(who.config, time.time())]
    print(f"contracts: {Path(contracts.__file__).resolve().parent}")
    print(f"engine: {pin.describe(pin.families(source[0].engine.writer_family, []))}")
    print(f"engine: {pin.describe_second(source[0].engine.second_writer_family)}")
    if second := source[0].engine.second_writer_family:
        print(ops.second_share_line(second, *ops.second_share(repo_traces(repo, git, ConfigDir(config_dir(env))).runs, second)))
    for w in warns:
        print("WARN " + w)
    if legacy := legacy_line(env):
        print(legacy)
    if old := layout_migrate.old_layout(who.config):
        print(f"WARN the config dir is in the old layout ({len(old)} places, first {old[0]}): "
              f"stop the loops, then run `{layout_migrate.COMMAND}`")
    fails = install_problems(plugin_root, env)
    for p in fails:
        print("FAIL " + p)
    found: list[env_checks.Finding] = [] if spawner is None else env_checks.all_findings(  # no spawner: a test that runs no process
        env.get("PATH"), env.get("TMPDIR"), config_dir(env), tuple(sys.version_info[:3]), spawner, git,
        lambda: bd_store(who.actor, repo).find(BeadQuery(status="open")), repo)
    sys.stdout.write("".join(f.line() + "\n" for f in found))
    fails += [f.text for f in found if f.level == "FAIL"]
    fails += rails.report(ConfigDir(config_dir(env)), install.GIT_HOOK, install.readable_install(plugin_root), git, repo, spawner,
                          [c.id for c in source[0].engine.gate_checks])
    fails += queue.report(real_stores(who.config), git, repo, f"origin/{base or 'main'}", time.time())
    if not warns and not found and not fails:
        print("ok: no setup problems found in " + repo)
    return 1 if fails else 0


