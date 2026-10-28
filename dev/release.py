#!/usr/bin/env python3
"""Release the plugin: one release at a time, the version from origin, the suite green, the marketplace bumped.

    python3 dev/release.py "message" [--bead ID --reason R] [--from-branch B] [--minor]
                           [--repo DIR] [--marketplace DIR]

A thin caller of src/taskloop/app/release/. Takes an OS lock (<config>/locks/release-*.lock): a second release waits in line and
prints who holds it. Works in a persistent clone of the repo's origin, <config>/release/<hash>/ (made on first use; the tool resets
it as it likes): the main checkout, dirty or on any branch, is never touched. In the clone: fetch, check out origin/main, replay
B's commits on it when --from-branch is given (B and its worktrees stay as they are), run the repo's gate (`just check`; skipped
when there is no justfile) and the full suite (red in either aborts with the output tail), commit the next patch version of
.claude-plugin/plugin.json (--minor: the minor) as "<version>: <message>", push under the land lock. The gate and suite are skipped,
and the log says "suite cache hit", when this exact tree already passed this exact command. When origin/main moved since the bump
it drops the bump, rebases, takes the next version and verifies again, still under the lock; a push refused all the same gets one
more such round. Then it tags v<version>, closes the bead, bumps the plugin's entry in the marketplace checkout (clean, on main),
pushes it, tags it `iorlas-task-loop-v<version>`, runs `claude plugin marketplace update` and `claude plugin update`. The installed
cache dir for the new version must exist afterwards: if not, the install runs once more, then the release exits non-zero naming the
failing command. Every release writes <config>/releases/last.json; a failed one also comments on --bead and ends with a one-line
"release FAILED" summary. Nothing is ever deleted: a plugin cache dir a live engine runs from stays.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "task-loop"))  # vendored.py: puts the vendored shelf packages on sys.path
sys.path.insert(0, str(HERE.parent / "src"))
import vendored  # noqa: E402, F401

from taskloop.app.release import flow  # noqa: E402

if __name__ == "__main__":
    sys.exit(flow.main(None, HERE.parent, __doc__.split("\n\n")[0]))
