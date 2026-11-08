"""Shared declarations of the public module surfaces of workspace packages."""

SURFACE = {"tlareas": ("policy", "testing"), "tlpipeline": ("api", "testing", "contracts")}
PACKAGE_ONLY = {
    "tlland": ('carry', 'checkout', 'cleanup', 'closing', 'cmds', 'contracts', 'domain.fix_text',
        'domain.queue_model', 'domain.queue_persist', 'domain.queue_reconcile', 'domain.queue_world', 'fix',
        'flake_book', 'forge', 'gate', 'host', 'lander', 'lander_host', 'lock_cmd', 'pr_land', 'push',
        'push_judge', 'queue_refs', 'rebase', 'record', 'section', 'stack', 'stackgate', 'store', 'testing',
        'tree', 'treecheck'),
    # api and the leaf modules tlwork and tlrelease already import (tl-e5t0.84): routing them through api.py would load land's evidence,
    # host and ports into every plan, review, write and release closure (+5 to +27 files per stage), so the guard names the leaves instead
    "tlgate": ("api", "testing", "contracts", "evidence", "authorization", "cache", "domain.planref", "domain.lint", "domain.affinity",
               "domain.names", "domain.inputs", "domain.specs", "domain.writer_split"),
    "tlslots": ("api", "testing"),
    "tlasks": ("api", "testing", "contracts"),
    "tlartifacts": ("api",),
    "tlwork": ("api", "testing"),
}
