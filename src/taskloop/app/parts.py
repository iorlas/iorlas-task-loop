"""The one list of stage parts: add each new stage part here.

The test in tests/rules/test_stage_parts.py fails until it is added.
"""
from tlkernel.dbparts import Part
from tlkernel.factoryparts import (
    ASKS,
    BEADCACHE,
    DASH,
    DISK,
    DURATION,
    FLAKE,
    INDEX,
    KV,
    LANES,
    LOOK,
    LOOP,
    PIPELINE,
    QUEUE,
    RECEIPT,
    RELEASE,
    REPORT,
    REPOS,
    RUNDOC,
    TICKET,
    WORK,
    WORKTREE,
)

from taskloop.app.checks.store import GATE
from taskloop.app.land.store import LAND
from taskloop.app.slots.store import SLOTS

STAGE_PARTS: tuple[Part, ...] = (
    DASH, PIPELINE, SLOTS, GATE, ASKS, KV, RELEASE, REPORT, LAND, WORK, LANES, LOOP, LOOK, RECEIPT, BEADCACHE, REPOS,
    TICKET, INDEX, WORKTREE, DISK, RUNDOC, DURATION, QUEUE, FLAKE,
)
