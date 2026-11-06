"""This repo's own gate check carries a pass over a base move: its profile names the closure command, and that command prints the files a
change's tests depend on (dev/affected.py --closure), so `land-stack` need not rerun the gate when main moved only outside them."""
import json
from pathlib import Path

import support.paths  # noqa: F401

from taskloop.contracts.config import load

ROOT = Path(__file__).resolve().parents[2]


def suite():
    profile = load(json.loads((ROOT / ".task-loop.json").read_text()))
    return next(c for c in profile.engine.checks if c.id == "suite")


def test_the_gate_check_names_the_closure_command():
    cmd = suite().closure_cmd
    assert cmd[-1] == "--closure" and (ROOT / cmd[-2]).is_file()
