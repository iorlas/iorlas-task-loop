"""The stop a step raises, as a stage sees it: why, and the outcome kind. The engine's `Blocked` (tlpipeline/blocked.py) is the one
subclass; a stage that catches a stop types it as this, so it needs nothing of the run slice."""
from tlkernel.kinds import Kind


class Stop(Exception):
    why: str
    kind: Kind
