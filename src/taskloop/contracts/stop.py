"""The stop a step raises, as a stage sees it: why, and the outcome kind. The engine's `Blocked` (app/run/blocked.py) is the one subclass; a
stage that catches a stop types it as this, so it needs nothing of the run slice."""
from taskloop.contracts.kinds import Kind


class Stop(Exception):
    why: str
    kind: Kind
