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
from tlrelease import catalog, manifest
from tlslots import watchdog
from tlslots.config import cfg_source

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
from taskloop.app.wire import slots as wslots
from taskloop.stores.delegate import real_route
from taskloop.stores.real import real_stores


def installed_problems(env: Env) -> list[str]:
    claude = claude_dir(env)
    version = catalog.installed_version(claude)
    installed = catalog.cache_dirs(claude).get(version)
    return [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)] if installed else []


def delegate_gap() -> str:
    lib = real_route().resolve()
    return ops.capability_gap(lib.contract if isinstance(lib, Resolved) else {})


def run(plugin_root: Path, env: Env, git: Git, who: Identity, spawner: Spawner | None = None) -> int:
    repo = git.toplevel(".") or os.getcwd()
    return ops.report(ops.DoctorFacts(
        repo=repo, contracts=lambda: Path(contracts.__file__).resolve().parent, migrate_command=layout_migrate.COMMAND,
        profile=lambda: profiles.report(git, repo, ReposStore(ConfigDir(config_dir(env)))),
        source=lambda: cfg_source(repo, git),
        slots=lambda: slot_warnings(
            lambda: wslots.slot_table(repo, who, git, time.time()),
            None if spawner is None else lambda: wslots.slot_env(repo, spawner=spawner, git=git, who=who),
            lambda env: watchdog.lines(watchdog.look(env))),
        path_link=lambda: path_link_line(env, config_dir(env)),
        git_warnings=lambda source: git_warnings(repo, source, git),
        layout_warnings=lambda source: layout_warnings(repo, source, git),
        bead_warnings=lambda: bead_lint_warnings(repo, lambda: bd_store(who.actor, repo)),
        clone_warnings=lambda: ops.clone_warnings(config_dir(env), git), capability_gap=delegate_gap,
        lost_runs=lambda: runlife.reconcile(who.config, time.time()),
        legacy=lambda: legacy_line(config_dir(env)), old_layout=lambda: layout_migrate.old_layout(who.config),
        install_problems=lambda: install_problems(plugin_root, config_dir(env), lambda: installed_problems(env)),
        findings=lambda: [] if spawner is None else env_checks.all_findings(
            env.get("PATH"), env.get("TMPDIR"), config_dir(env), tuple(sys.version_info[:3]), spawner, git,
            lambda: bd_store(who.actor, repo).find(BeadQuery(status="open")), repo),
        rails=lambda source: rails.report(ConfigDir(config_dir(env)), install.GIT_HOOK, install.readable_install(plugin_root),
                                          git, repo, spawner, [c.id for c in source[0].engine.gate_checks]),
        queue=lambda base: queue.report(real_stores(who.config), git, repo, f"origin/{base or 'main'}", time.time()),
    ))
