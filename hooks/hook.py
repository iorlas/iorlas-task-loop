#!/usr/bin/env python3
"""The task-loop plugin's hooks: `hook.py pretool | session-start | precompact`, the event JSON on stdin (see hooks.json).
Each must finish in well under a second (tests/test_hook.py times a real process): the PreToolUse one imports only the rules."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))  # vendored.py: the vendored shelf packages the stores import
sys.path.insert(0, str(ROOT / "src"))
import vendored  # noqa: E402,F401

from taskloop.hook.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin.read(), ROOT))
