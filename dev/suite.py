#!/usr/bin/env python3
"""The land gate: the full suite as parallel shards (taskloop.app.release.suite), exit 0 when green, 1 when red.

    python3 dev/suite.py [--repo DIR] [--record]      (default: the checkout this file is in)

The runner lives in src/taskloop/app/release/suite.py; this is only its command line.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "task-loop"))  # vendored.py: the vendored shelf packages
sys.path.insert(0, str(HERE.parent / "src"))
import vendored  # noqa: E402, F401

from taskloop.app.release import suite  # noqa: E402
from taskloop.app.release.shell import Abort  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="suite.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="the checkout whose tests run (default: this one)")
    ap.add_argument(
        "--record", action="store_true", help="also write each test's seconds to tests/durations.json (the splitter balances on it)"
    )
    args = ap.parse_args(argv)
    try:
        suite.host_suite(HERE.parent, Path(args.repo), args.record)
    except Abort as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
