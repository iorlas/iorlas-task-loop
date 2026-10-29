"""Counts the Python interpreter starts of a suite run: one line per start, appended at exit to the file `count.sh` names.

    tests/support/pystarts/count.sh /tmp/starts.txt -n 8 -q       # prints the count; the file lists the starts

`count.sh` drops a .pth into the dev venv (so a child whose env lacks PYTHONPATH or PROBE_OUT is counted too: dashboard servers, nested
pytest) and removes it when the run ends. Each line is the start's command line (the first 120 characters), so
`cut -c1-60 | sort | uniq -c` shows which one-liners and scripts make them."""
import atexit
import os
import sys


def note(out: str) -> None:
    if getattr(sys, "_pystarts_noted", False):  # a .pth in a venv is read twice
        return
    sys._pystarts_noted = True  # pyrefly: ignore

    def write() -> None:
        try:
            with open("/proc/self/cmdline", "rb") as f:
                line = f.read().replace(b"\0", b" ").decode("utf-8", "replace")[:120]
            with open(out, "a", encoding="utf-8") as fh:
                test = os.environ.get("PYTEST_CURRENT_TEST", "-").split(" ")[0]  # the test that was running in the parent
                fh.write(test + "\t" + line.replace("\n", " ") + "\n")
        except OSError:
            pass

    atexit.register(write)
