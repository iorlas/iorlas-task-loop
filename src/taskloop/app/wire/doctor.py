"""`tl doctor`: what is off in the repo's setup for the loop, one line each, and the repo-profile report."""
import os
import sys
import time
from pathlib import Path

import tlkernel as contracts
from tlkernel import runlife
from tlkernel.beadsport import BeadQuery
from tlkernel.delegateport import Resolved
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner
from tlkernel.rowstores import ReposStore
from tlslots import watchdog
from tlslots.config import cfg_source, configured_slots

from taskloop.adapters import layout_migrate
from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.app.doctor import env_checks, install, ops, profiles, queue, rails
from taskloop.app.doctor.setup_checks import (
    bead_lint_warnings,
    git_warnings,
    install_problems,
    layout_warnings,
    legacy_line,
    path_link_line,
    slot_warnings,
)
from taskloop.app.release import catalog, manifest
from taskloop.app.wire import slots as wslots
from taskloop.stores.delegate import real_route
from taskloop.stores.real import real_stores


def run(plugin_root: Path, env: Env, git: Git, who: Identity, spawner: Spawner | None = None) -> int:
    repo = git.toplevel(".") or os.getcwd()
    if profiles.report(git, repo, ReposStore(ConfigDir(config_dir(env)))):  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = cfg_source(repo, git)
    _, base, commit = source
    print(f"config: .task-loop.json from base {base} at commit {commit}" if commit else
          f"config: .task-loop.json from working tree {repo} (base {base} unresolved; no commit read)")
    now = time.time()
    slot_line, slot_warns = slot_warnings(
        lambda: wslots.slot_table(repo, who, git, now),
        None if spawner is None else lambda: wslots.slot_env(repo, spawner=spawner, git=git, who=who),
        lambda env: watchdog.lines(watchdog.look(env)), configured_slots(repo, git))
    print(slot_line)
    link_line, foreign = path_link_line(env, config_dir(env))
    if not foreign:
        print(link_line)  # a foreign `tl` is a WARN below
    warns = git_warnings(repo, source, git) + layout_warnings(repo, source, git)
    warns += bead_lint_warnings(repo, lambda: bd_store(who.actor, repo)) + slot_warns
    warns += [link_line] if foreign else []
    warns += ops.clone_warnings(config_dir(env), git)
    lib = real_route().resolve()
    warns += [gap] if (gap := ops.capability_gap(lib.contract if isinstance(lib, Resolved) else {})) else []
    warns += [f"run {r} is lost: its process is gone and it recorded no end" for r in runlife.reconcile(who.config, time.time())]
    print(f"contracts: {Path(contracts.__file__).resolve().parent}")
    for line in ops.product_lines(source[0].engine.writer_exec, source[0].engine.reviewer_other_family):
        print(f"engine: {line}")
    for w in warns:
        print("WARN " + w)
    if legacy := legacy_line(config_dir(env)):
        print(legacy)
    if old := layout_migrate.old_layout(who.config):
        print(f"WARN the config dir is in the old layout ({len(old)} places, first {old[0]}): "
              f"stop the loops, then run `{layout_migrate.COMMAND}`")
    def verify_installed() -> list[str]:
        claude = claude_dir(env)
        version = catalog.installed_version(claude)
        installed = catalog.cache_dirs(claude).get(version)
        return [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)] if installed else []

    fails = install_problems(plugin_root, config_dir(env), verify_installed)
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


