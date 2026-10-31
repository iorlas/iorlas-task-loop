"""The entry of hooks/hook.py: the event name picks the module, so a PreToolUse call never imports the stores."""
import importlib
import sys
from collections.abc import Mapping
from pathlib import Path


def main(argv: list[str], stdin_text: str, plugin_root: Path, environ: Mapping[str, str] | None = None) -> int:
    """`hook.py pretool | session-start | precompact | githook NAME TL ARGS`. The hook's stdout goes to Claude Code;
    a failure is silent (exit 0)."""
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
    except Exception:
        return 0
    if out:
        print(out)
    return 0
