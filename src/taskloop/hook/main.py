"""The entry of hooks/hook.py: the event name picks the module, so a PreToolUse call never imports the stores."""
import importlib
import sys
from pathlib import Path


def main(argv: list[str], stdin_text: str, plugin_root: Path) -> int:
    """`hook.py pretool | session-start | precompact | prepush TL REMOTE URL`. The hook's stdout goes to Claude Code;
    a failure is silent (exit 0)."""
    event = argv[0] if argv else ""
    try:
        if event == "pretool":
            out = importlib.import_module("taskloop.hook.pretool").main(stdin_text)
        elif event == "prepush":  # git's pre-push hook (argv: the tl command, git's remote and url): the exit code is the verdict
            return importlib.import_module("taskloop.hook.prepush").entry(argv[1:], stdin_text)
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
