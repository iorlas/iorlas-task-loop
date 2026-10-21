"""`tl loop` (or run-task --slot any --wait) with its waits cut to fractions of a second (the race test's loops and its
waiter): the same code, seeded jitter.

    python3 loop_fast.py SEED tl-args...
"""

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "task-loop"))
import loop  # noqa: E402
import tl  # noqa: E402

random.seed(sys.argv[1])
loop.POLL, loop.PAUSE_RETRY, loop.MARGIN = 0.2, 2, (0.1, 0.4)
loop.AREA_POLL, tl.TICKET_POLL = 0.3, (0.1, 0.3)
_nap = loop.nap
loop.nap = lambda secs, repo=None, until=0: _nap(min(secs, random.uniform(0.1, 0.4)), repo, until)
sys.exit(tl.main(sys.argv[2:]))
