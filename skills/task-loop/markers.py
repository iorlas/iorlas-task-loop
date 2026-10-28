#!/usr/bin/env python3
"""The conflict-marker check: print the lines and exit 1 when the tree holds `<<<<<<<` or `>>>>>>>` markers, else exit 0."""
import subprocess
import sys

PATTERN = r"^(<<<<<<<|>>>>>>>)( |$)"


def main() -> int:
    r = subprocess.run(["git", "grep", "-n", "-I", "-E", PATTERN, "--", "."], capture_output=True, text=True, check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return 1 if r.returncode == 0 else 0 if r.returncode == 1 else r.returncode


if __name__ == "__main__":
    sys.exit(main())
