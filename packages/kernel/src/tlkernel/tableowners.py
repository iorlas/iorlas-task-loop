"""Owner roles for the shared factory database tables."""

# One owner role per table: other actors submit writes through that role's store.
# The loop owns leases; the engine records AskStore writes, including
# owner answers. Lease reconciliation must use the loop store's guarded verbs,
# not cas_update (leases and the ask ledger have no revision column).
OWNERS: dict[str, str] = {
    "source": "index",
    "bead": "index",  # Cached tracker projection; parent is an opaque field.
    "run": "engine",
    "attempt": "engine",  # Reconcile may mark lost only after the loop guards the expired lease.
    "step": "engine",
    "lease": "loop",
    "check_pass": "gate",
    "check_round": "gate",
    "ask": "engine",
    "ask_ledger": "engine",
    "park": "engine",  # asks-owned park rows, written through ParkStore
    "queue_doc": "engine",  # land queue runner and tree assertions through Stores
    "flake_doc": "engine",  # land flake scoring through FlakeBook

    "run_doc": "engine",  # run counters, handoff, prepare and once-per-run notes through rundocs
    "duration_doc": "gate",  # check duration history through the checks store
    "receipt_doc": "owner",  # dashboard command responses through api/writes.py
    "bead_doc": "index",  # tracker projection observations through beadrows
    "repos_doc": "engine",  # repository registration through app/track/trail.py
    "ticket_doc": "loop",  # slot ticket allocation through TicketRows
    "index_doc": "index",  # indexer pass freshness
    "worktree_doc": "engine",  # worktree creation and cleanup through app/slots/owned.py
    "disk_doc": "loop",  # hourly free-space samples through app/doctor/disk.py
    "loop_doc": "loop",  # loop rests/cleanup and owner stop commands through LoopFiles
    "look_doc": "engine",  # engine filing and owner answers through LookRows
    "followup": "engine",  # the land's outbox (app/land/store.py)
    "effect": "engine",
    "wait": "loop",  # pipeline waits; parks live in the asks-owned park table
    "signal": "owner",
    "timed": "engine",  # what the engine log's end records timed: tl runs show|slow read these
    "report_doc": "engine",  # the report part's reflect digest state (tl reflect)
    "accounts_doc": "engine",  # the accounts part's status records (loop chore, tl usage)
    "work_doc": "engine",  # the work part's decision-record cache (plan refreshes it)
    "release_doc": "engine",  # the release part's pin and last result (tl pin, tl release)
    "checkpoint_section": "engine",
    "checkpoint": "engine",  # one row per bead across runs; the engine writes it with the revision it read
}
