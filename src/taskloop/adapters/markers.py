#!/usr/bin/env python3
"""The conflict-marker check: print the lines and exit 1 when the tree holds `<<<<<<<` or `>>>>>>>` markers, else exit 0."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/: also run by path from a slot
from taskloop.adapters import procs

PATTERN = r"^(<<<<<<<|>>>>>>>)( |$)"


def main() -> int:
    r = procs.run(["git", "grep", "-n", "-I", "-E", PATTERN, "--", "."])
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return 1 if r.returncode == 0 else 0 if r.returncode == 1 else r.returncode


if __name__ == "__main__":
    sys.exit(main())
