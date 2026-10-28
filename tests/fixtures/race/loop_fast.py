"""`tl loop` (or run-task --slot any --wait) with its waits cut to fractions of a second (the race test's loops and its
waiter): the same code, seeded jitter.

    python3 loop_fast.py SEED tl-args...
"""

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "task-loop"))
import tl  # noqa: E402  (before the src import: puts src/ on sys.path)
from taskloop.app.loop.core import Core  # noqa: E402
from taskloop.app.slots import env as slots_env, line as slots_line  # noqa: E402

random.seed(sys.argv[1])
slots_env.TICKET_POLL = slots_line.TICKET_POLL = (0.1, 0.3)  # pyrefly: ignore[bad-assignment]  # the loop's own waits are the `loop` block of the repo's .task-loop.json (dev/race.py)
_nap = Core.nap
Core.nap = lambda self, secs, until=0.0: _nap(self, min(secs, random.uniform(0.1, 0.4)), until)
sys.exit(tl.main(sys.argv[2:]))
