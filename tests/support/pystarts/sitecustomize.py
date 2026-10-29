"""Counts the Python interpreter starts of a suite run: one line per start, appended at exit to $PROBE_OUT.

    PROBE_OUT=/tmp/starts.txt PYTHONPATH=tests/support/pystarts uv run pytest -n 4

`wc -l /tmp/starts.txt` is the count; each line is the start's command line (the first 120 characters), so `cut -c1-60 | sort | uniq -c`
shows which one-liners and scripts make them."""
import atexit
import os


def _note() -> None:
    try:
        with open("/proc/self/cmdline", "rb") as f:
            line = f.read().replace(b"\0", b" ").decode("utf-8", "replace")[:120]
        with open(os.environ["PROBE_OUT"], "a", encoding="utf-8") as out:
            out.write(line.replace("\n", " ") + "\n")
    except (KeyError, OSError):
        pass


if os.environ.get("PROBE_OUT"):
    atexit.register(_note)
