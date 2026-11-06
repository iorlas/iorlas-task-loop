"""``python -m shelf_vendor --vendor-dir D --manifest M [--shelf S] sync NAME [--tag T] | check``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from shelf_vendor import Vendor


def _shelf(explicit: str | None) -> Path | None:
    for cand in (explicit, os.environ.get("SHELF_HOME"), Path.home() / "Workspaces" / "shelf"):
        if cand and (Path(cand) / ".git").exists():
            return Path(cand)
    return None


def _say(text: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shelf_vendor", description=__doc__)
    ap.add_argument("--vendor-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--shelf", help="shelf checkout (default: $SHELF_HOME, then ~/Workspaces/shelf)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("name")
    s.add_argument("--tag")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    vendor = Vendor(args.vendor_dir, args.manifest)
    shelf = _shelf(args.shelf)
    if args.cmd == "sync":
        if shelf is None:
            _say("vendor: no shelf checkout (set SHELF_HOME or pass --shelf)", err=True)
            return 2
        e = vendor.sync(args.name, args.tag, shelf=shelf)
        _say(f"vendor: {e['name']} synced from {e['shelf_tag']} ({e['shelf_commit'][:12]}) tree_hash {e['tree_hash'][:12]}")
        return 0
    drift, warnings = vendor.check(shelf)
    for line in warnings:
        _say(f"vendor: NEWER {line}", err=True)
    for line in drift:
        _say(f"vendor: DRIFT {line}", err=True)
    if not drift:
        n = len(vendor.load())
        _say(f"vendor: ok ({n} package{'' if n == 1 else 's'}{', checked against the shelf tag' if shelf else ''})")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
