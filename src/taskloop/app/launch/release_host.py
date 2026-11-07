"""Bind release effects to the shell adapters and authorization stores."""
from tlgate import authorization
from tlkernel.paths import ConfigDir
from tlrelease.gate import GateHost

from taskloop.adapters import beadtools, gitrepo, ident, landlock
from taskloop.stores.real import real_stores


def release_host() -> GateHost:
    return GateHost(
        config_dir=ident.config_dir, claude_dir=ident.claude_dir, identity=ident.identity, plugin_root=ident.PLUGIN_ROOT,
        land_lock_path=landlock.land_lock_path, os_lock=landlock.os_lock, bd_store=beadtools.bd_store, repo_root=gitrepo.repo_root,
        memo_for=lambda git, wt, cfg, tree, base, env: authorization.memo_for(
            real_stores(ConfigDir(ident.config_dir(env))), git, wt, cfg, tree, base, env),
    )
