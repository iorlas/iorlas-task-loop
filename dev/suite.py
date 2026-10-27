#!/usr/bin/env python3
"""The land gate: the full suite as parallel shards (release.suite), exit 0 when green, 1 when red.

    python3 dev/suite.py [--repo DIR]      (default: the checkout this file is in)

One copy of the runner lives in release.py; this is only its command line. Python 3.8+, standard library only.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="suite.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="the checkout whose tests run (default: this one)")
    args = ap.parse_args(argv)
    try:
        release.suite(args.repo)
    except release.Abort as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
