"""A counting lease across processes: up to ``limit`` holders of a named resource.

Each unit is one :mod:`process_lock` flock (``<root>/<name>-<slot>.lock``), so the kernel frees a unit when its holder dies,
``kill -9`` included. Waiting is a poll; ``cancel`` and ``timeout`` end it with nothing held.
"""

from any_lease.leases import Held, HeldAll, LeaseCancelledError, Leases, LeaseTimeoutError, Occupant, Waiting

__all__ = ["Held", "HeldAll", "LeaseCancelledError", "LeaseTimeoutError", "Leases", "Occupant", "Waiting"]
