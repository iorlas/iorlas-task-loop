#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = ["msgspec==0.22.0"]
# ///
"""The task-loop plugin's hooks: `hook.py pretool | session-start | precompact`, the event JSON on stdin (see hooks.json).
PreToolUse runs before every Bash call, under plain `python3`, and imports only the rules: no msgspec, no record model (the
.importlinter contract and tests/test_hook.py hold it). SessionStart and PreCompact read and write records (the handoff, the `tl` shim),
so hooks.json runs them with `uv run --script` and the dependencies this header declares."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # importing taskloop puts the vendored shelf packages the stores import on sys.path

from taskloop.hook.main import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    quiet = args[:1] == ["githook"] and args[1:2] not in (["pre-push"], ["post-rewrite"])  # only these two are fed on stdin
    sys.exit(main(args, "" if quiet else sys.stdin.read(), ROOT, dict(os.environ)))
