#!/usr/bin/env python3
"""List the runs to turn into replay cases: the newest N that landed and kept their node answers.

    python3 dev/record_corpus.py RUNS_DIR [--last 30]

RUNS_DIR is <config>/task-loop/runs. A run counts when its engine.jsonl holds a `land_receipt` record and its folder still has a plan, a
write and a review answer (plan.json, write-N.json, review-N.json). For each, this prints the dev/record_exchange.py commands that
record its planner, writer and reviewer exchanges (bead.json comes from `bd show ID --json`, so run them where the beads are). It
writes nothing: what goes into tests/fixtures/exchanges is the owner's call, since the answers carry repo content. Stdlib only."""
import argparse
import json
import sys
from pathlib import Path

NEEDED = ("plan.json", "write-*.json", "review-*.json")
ROLES = ("planner", "writer", "reviewer")


def landed(folder: Path) -> bool:
    """The run's log holds a land_receipt record (a torn or missing log is not one)."""
    try:
        for line in (folder / "engine.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("kind") == "land_receipt":
                    return True
            except ValueError:
                continue
    except OSError:
        return False
    return False


def pick(root: Path, last: int) -> list[Path]:
    """The newest `last` run folders (folder names are ULIDs: later sorts later) that landed and kept all three kinds of answer."""
    folders = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    good = [p for p in folders if landed(p) and all(any(p.glob(g)) for g in NEEDED)]
    return good[:last]


def commands(root: Path, last: int) -> list[str]:
    """The record_exchange command of every role of every picked run, then a count line (a comment)."""
    picked = pick(root, last)
    lines = [f"python3 dev/record_exchange.py {f} {role} real-{f.name}-{role} --bead BEAD.json --source 'run {f.name}'"
             for f in picked for role in ROLES]
    return [*lines, f"# {len(picked)} landed run(s) with answers"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs_dir", type=Path)
    ap.add_argument("--last", type=int, default=30)
    a = ap.parse_args(argv)
    print("\n".join(commands(a.runs_dir, a.last)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
