"""Argument wiring and output for `tl wait`."""
import argparse
import time
from argparse import Namespace
from collections.abc import Callable
from typing import Any

from tlkernel.askstore import AskStore
from tlkernel.paths import ConfigDir

from taskloop.app.asks import owner_verbs as requests

ASK = requests.ASK
CODES = requests.CODES
CRASHED = requests.CRASHED
ENDED_NOT_OK = requests.ENDED_NOT_OK
ENDED_OK = requests.ENDED_OK
NO_RUN = requests.NO_RUN
POLL = requests.POLL
TIMEOUT = requests.TIMEOUT
asked = requests.asked
repo_runs = requests.repo_runs
verdict = requests.verdict

Out = Callable[[str], None]


def wait(a: Namespace, cfg: ConfigDir, asks: AskStore, repo: str, out: Out = print,
         now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> int:
    code, line = requests.wait(cfg, asks, repo, getattr(a, "bead", None), getattr(a, "timeout", None), now, sleep)
    out(line)
    return code


def add_parser(sp: Any) -> None:
    p = sp.add_parser("wait", help="block until a run ends or an ask opens; one line, the exit code says which",
                      epilog=CODES, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bead", metavar="ID", help="wait for the newest run of this bead (or an ask on it)")
    g.add_argument("--any", action="store_true", help="wait for any run of this repo's loop that is live now (or any ask of the repo)")
    p.add_argument("--timeout", type=float, metavar="S", help=f"give up after S seconds (exit {TIMEOUT})")
    p.add_argument("--repo")
