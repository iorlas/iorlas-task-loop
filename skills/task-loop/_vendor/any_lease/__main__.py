"""``python -m any_lease run NAME LIMIT LABEL -- command...``: hold one unit of NAME for the lifetime of a command."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from any_lease.leases import Leases, Waiting

_HELD_ENV = "ANY_LEASE_HELD"  # names held by an ancestor wrapper, colon-separated: a nested run of the same name just runs
_ROOT_ENV = "ANY_LEASE_ROOT"
_FORWARDED = (signal.SIGINT, signal.SIGTERM)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m any_lease")
    sub = parser.add_subparsers(dest="verb", required=True)
    run = sub.add_parser("run", help="hold a unit while a command runs")
    run.add_argument("name")
    run.add_argument("limit", type=int)
    run.add_argument("label")
    run.add_argument("--root", type=Path, default=os.environ.get(_ROOT_ENV), help=f"lease folder (default ${_ROOT_ENV})")
    run.add_argument("--poll", type=float, default=0.5)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.root is None:
        parser.error("a command after -- and --root (or $ANY_LEASE_ROOT) are required")
    held = [h for h in os.environ.get(_HELD_ENV, "").split(":") if h]
    if args.name in held:
        return _run(command, held)
    leases = Leases(Path(args.root).expanduser())
    told = False

    def on_wait(w: Waiting) -> None:
        nonlocal told
        if not told:
            told = True
            who = ", ".join((o.holder.label or "unknown") if o.holder else "unknown" for o in w.occupants)
            _say(f"{args.label} waits for {w.name} ({w.limit} busy: {who})")

    began = time.monotonic()
    meta = {"cwd": str(Path.cwd())}
    with leases.acquire(args.name, args.limit, label=args.label, meta=meta, on_wait=on_wait, poll=args.poll) as got:
        if told:
            _say(f"{args.label} got {args.name} slot {got.slot} after {int(time.monotonic() - began)}s")
        return _run(command, [*held, args.name])


def _say(text: str) -> None:
    sys.stderr.write(f"any-lease: {text}\n")
    sys.stderr.flush()


def _run(command: list[str], held: list[str]) -> int:
    """Run ``command``, handing it SIGINT and SIGTERM, and return its exit code (128+n when a signal ended it)."""
    child: subprocess.Popen[bytes] | None = None
    pending: list[int] = []

    def forward(signum: int, _frame: object) -> None:
        if child is None:
            pending.append(signum)
        else:
            child.send_signal(signum)

    previous = {sig: signal.signal(sig, forward) for sig in _FORWARDED}
    try:
        # exec keeps the signal mask: a wrapper started with SIGINT/SIGTERM blocked would hand its child a command that ignores both.
        child = subprocess.Popen(
            command,
            env={**os.environ, _HELD_ENV: ":".join(held)},
            preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, []),  # noqa: PLW1509
        )
        for signum in pending:
            child.send_signal(signum)
        while True:  # short slices, so a Python signal handler always gets to run
            try:
                code = child.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
            return code if code >= 0 else 128 - code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
