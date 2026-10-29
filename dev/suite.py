#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = ["msgspec==0.22.0"]
# ///
"""The land gate: the full suite through pytest-xdist workers (taskloop.app.release.suite), exit 0 when green, 1 when red.

    uv run --script dev/suite.py [--repo DIR]      (default: the checkout this file is in)

The runner lives in src/taskloop/app/release/suite.py; this is only its command line.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))  # importing taskloop puts the vendored shelf packages on sys.path

from taskloop.app.release import suite  # noqa: E402
from taskloop.app.release.shell import Abort  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="suite.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="the checkout whose tests run (default: this one)")
    args = ap.parse_args(argv)
    try:
        suite.host_suite(HERE.parent, Path(args.repo))
    except Abort as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
