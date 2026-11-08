"""The one list of stage parts: add each new stage part here.

The test in tests/rules/test_stage_parts.py fails until it is added.
"""
from tlgate.store import GATE
from tlkernel.dbparts import Part
from tlkernel.factoryparts import (
    ACCOUNTS,
    ASKS,
    BEADCACHE,
    DASH,
    DISK,
    DURATION,
    FLAKE,
    INDEX,
    LOOK,
    LOOP,
    PIPELINE,
    QUEUE,
    RECEIPT,
    RELEASE,
    REPORT,
    REPOS,
    RUNDOC,
    SLOTS,
    TICKET,
    WORK,
    WORKTREE,
)
from tlland.store import LAND

STAGE_PARTS: tuple[Part, ...] = (
    DASH, PIPELINE, SLOTS, GATE, ASKS, RELEASE, REPORT, LAND, WORK, ACCOUNTS, LOOP, LOOK, RECEIPT, BEADCACHE, REPOS,
    TICKET, INDEX, WORKTREE, DISK, RUNDOC, DURATION, QUEUE, FLAKE,
)
