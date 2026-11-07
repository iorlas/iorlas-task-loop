"""Bind release effects to the shell adapters and authorization stores."""
from tlgate import authorization
from tlkernel.paths import ConfigDir
from tlrelease.host import ReleaseHost

from taskloop.adapters import beadtools, gitrepo, ident, landlock, suiteout
from taskloop.stores.real import real_stores


def release_host() -> ReleaseHost:
    return ReleaseHost(
        config_dir=ident.config_dir, claude_dir=ident.claude_dir, identity=ident.identity, plugin_root=ident.PLUGIN_ROOT,
        land_lock_path=landlock.land_lock_path, os_lock=landlock.os_lock, bd_store=beadtools.bd_store, repo_root=gitrepo.repo_root,
        suite_report=suiteout.failure_report, failing_tests=suiteout.failing_tests,
        memo_for=lambda git, wt, cfg, tree, base, env: authorization.memo_for(
            real_stores(ConfigDir(ident.config_dir(env))), git, wt, cfg, tree, base, env),
    )
