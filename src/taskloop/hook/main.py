"""The entry of hooks/hook.py: the event name picks the module, so a PreToolUse call never imports the stores."""
from __future__ import annotations

import importlib
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

# What an exception in a hook means, one table: PreToolUse, SessionStart and PreCompact must never break a session (fail open, exit 0);
# the pre-push githook is the delivery gate, so anything that goes wrong in it refuses the push (fail closed, exit 1).
FAIL_OPEN, FAIL_CLOSED = 0, 1
FAIL_MODE: Mapping[str, int] = MappingProxyType({"pretool": FAIL_OPEN, "session-start": FAIL_OPEN, "precompact": FAIL_OPEN,
                                                 "githook": FAIL_OPEN, "githook pre-push": FAIL_CLOSED})


def fail_exit(argv: list[str]) -> int:
    """The exit code for an exception while handling `argv`: the most specific FAIL_MODE row, an unlisted event fails open."""
    return FAIL_MODE.get(" ".join(argv[:2]), FAIL_MODE.get(argv[0] if argv else "", FAIL_OPEN))


def main(argv: list[str], stdin_text: str, plugin_root: Path, environ: Mapping[str, str] | None = None) -> int:
    """`hook.py pretool | session-start | precompact | githook NAME TL ARGS`. The hook's stdout goes to Claude Code;
    a failure is silent (exit 0), except pre-push failures refuse delivery (exit 1)."""
    event = argv[0] if argv else ""
    try:
        if event == "pretool":
            out = importlib.import_module("taskloop.hook.pretool").main(stdin_text)
        elif event == "githook":  # a hook of tl's hooks dir (argv: name, tl, git's arguments): the exit code is the verdict
            return importlib.import_module("taskloop.hook.prepush").githook(argv[1], argv[2:], stdin_text, environ or {})
        elif event in ("session-start", "precompact"):
            out = importlib.import_module("taskloop.hook.session").entry(event, stdin_text, plugin_root)
        else:
            print(f"hook.py: unknown event {event!r}", file=sys.stderr)
            return 2
    except Exception as err:
        code = fail_exit(argv)
        if code:
            print(f"tl pre-push: refused: delivery judge unavailable: {err}", file=sys.stderr)
        return code
    if out:
        print(out)
    return 0
