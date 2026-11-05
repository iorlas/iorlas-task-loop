#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = ["msgspec==0.22.0"]
# ///
"""Release the plugin: one release at a time, the version from origin, the suite green, the marketplace bumped.

    uv run --script dev/release.py "message" [--bead ID --reason R] [--from-branch B] [--minor]
                           [--repo DIR] [--marketplace DIR]
    uv run --script dev/release.py --devbox-ok VERSION

A thin caller of src/taskloop/app/release/, always running origin/main's release code: once the clone is on origin/main, a launching
checkout whose src/ or dev/release.py differs (it lags; nothing updates it) is replaced by an exec of the clone's dev/release.py with the
same arguments (--repo made explicit), after the lock is dropped so the exec'd release takes it. Takes an OS lock
(<config>/locks/release-*.lock): a second release waits in line and prints who holds it. Works in a persistent clone of the repo's origin,
<config>/release/<hash>/ (made on first use; the tool resets it as it likes): the main checkout, dirty or on any branch, is never touched.
In the clone: fetch, check out origin/main, replay B's commits on it when --from-branch is given (B and its worktrees stay until the
release has pushed and installed), run the repo's gate (`just check`; skipped when there is no justfile) and the profile's suite check
(`just test`: the tests the change can break; red in either aborts with the output tail),
commit the next patch version of .claude-plugin/plugin.json (--minor: the minor) as "<version>: <message>",
push under the land lock. The gate and suite are cached by pre-bump tree and command. When origin/main moves, the release drops the
bump, rebases and verifies the changed tree outside the land lock, then takes the lock again to push (three attempts maximum).
A successful push enters the devbox ring. Releases have no minimum interval.
After the devbox canary succeeds, --devbox-ok VERSION publishes devbox-ok/vVERSION on origin for the Mac's tl pin.
Rollback to an older installed version needs no new acknowledgement. The post-bump check validates the version and manifest,
and permits only those two files to differ from the tested tree. Three lost push races stop the release. There is no CI gate (D-11).
Then it tags v<version>, closes the bead, bumps the plugin's entry in the
marketplace checkout (clean, on main), pushes it, tags it `iorlas-task-loop-v<version>`, runs `claude plugin marketplace update` and
`claude plugin update`. The installed cache dir for the new version must exist afterwards: if not, the install runs once more, then the
release exits non-zero naming the failing command. Every release writes <config>/releases/last.json; a failed one also comments on --bead
and ends with a one-line "release FAILED" summary. After a successful push and install, --from-branch B's worktrees (plain `git worktree
remove`, never --force) and B itself are removed; any failure keeps both. A plugin cache dir a live engine runs from stays.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))  # importing taskloop puts the vendored shelf packages on sys.path

import taskloop  # noqa: E402, F401  (turns lazy imports on for our modules)

# A release rebases and bumps the very clone it runs from, so a module imported lazily mid-run comes from the new tree (0.23.178:
# the old flow called the new tidy.drop_branch and failed). Load the whole release now, from the tree it started on.
if hasattr(sys, "set_lazy_imports"):
    sys.set_lazy_imports("normal")  # only explicit `lazy import` statements stay lazy; we write none
from taskloop.app.release import flow  # noqa: E402
from taskloop.app.wire import closeguard, real  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402

if __name__ == "__main__":
    process = snapshot()  # the one place this script takes the process environment
    doc = __doc__.split("\n\n")[0]
    sys.exit(flow.main(None, HERE.parent, real.spawner(process), real.git(process), process, closeguard.close_released, doc))
