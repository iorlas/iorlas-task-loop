"""The one list of stage parts: add each new stage part here.

The test in tests/rules/test_stage_parts.py fails until it is added.
"""
from taskloop.app.land.store import LAND
from taskloop.contracts.dbparts import Part
from taskloop.contracts.factoryparts import ASKS, DASH, GATE, KV, PIPELINE, RELEASE, REPORT, SLOTS, WORK

STAGE_PARTS: tuple[Part, ...] = (DASH, PIPELINE, SLOTS, GATE, ASKS, KV, RELEASE, REPORT, LAND, WORK)
