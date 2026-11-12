"""The install commands' surface: `tl version [--json]`, `tl install REV --checkout PATH`, `tl pin REV` and `tl pin --clear`
(tl-8bh9.8.3 sections 6.1-6.3).

`tl version` is read-only: this process's install (`sys.prefix` and the manifest beside it, through `installs.state`) and
the pin of the machine config in use; no factory.db, no lock, no listing of the installs. `tl install` runs the one
operation `install_op.install` over `cli_composition.install_ports` and prints its progress as it goes; `tl pin` runs
`pin_op` over the local files (no Git, no factory.db, no config file read). Text only.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from taskloop import cli_composition, install_op, pin_file, pin_op
from taskloop.install_op import Installed, Refused, Unavailable
from taskloop.installs import LocalFiles, Manifest, Reads, running
from taskloop.pin_file import Pin, PinInvalid
from taskloop.pin_op import Cleared, Pinned, Was

EFFECT: Final = ("Takes effect at the next start of tl; a running `tl step rounds` and its entries keep their version. Drain "
                 "before pinning: stop the rounds, wait for or abandon running attempts.")

type Parsers = argparse._SubParsersAction[argparse.ArgumentParser]


@dataclass(frozen=True)
class Version:
    prefix: Path
    running: Manifest | None  # None: unmanaged
    pin_file: Path | None  # None: the config path names no file
    pinned: Pin | PinInvalid | None


def describe(prefix: Path, home: Path, config: str | None, files: Reads) -> Version:
    """The running install is the complete install under this home's installs root whose `venv` is `prefix` (both
    resolved); the pin is the one start reads."""
    path = pin_file.pin_path(config, home)
    pinned = pin_file.nameless(config) if path is None else pin_file.read(files, path)
    return Version(prefix.resolve(), running(files, prefix, home), path, pinned)


def _named(commit: str, tag: str | None) -> str:
    """The one human form of an install or pin: `<commit12>` or `<commit12> (<tag>)`."""
    return commit[:12] if tag is None else f"{commit[:12]} ({tag})"


def lines(version: Version) -> list[str]:
    running = version.running
    shown = "unmanaged" if running is None else _named(running.commit, running.tag)
    match version.pinned:
        case None:
            pinned = "Pinned: none"
        case PinInvalid(detail=detail):
            pinned = f"Pinned: invalid ({version.pin_file or detail})"
        case Pin(commit=commit, tag=tag, pinned_at=at):
            pinned = f"Pinned: {_named(commit, tag)} since {at} ({version.pin_file})"
    return [f"Running: {shown} ({version.prefix})", pinned]


def data(version: Version) -> dict[str, object]:
    """`running` is `tl install`'s verification answer; an invalid pin is `{"invalid": <why>, "file": ...}`."""
    running = version.running
    pinned: dict[str, object] | None
    file = None if version.pin_file is None else str(version.pin_file)
    match version.pinned:
        case None:
            pinned = None
        case PinInvalid(detail=detail):
            pinned = {"invalid": detail, "file": file}
        case Pin(commit=commit, tag=tag, pinned_at=at):
            pinned = {"commit": commit, "tag": tag, "pinned_at": at, "file": file}
    return {"running": {"prefix": str(version.prefix), "install": None if running is None else running.commit,
                        "tag": None if running is None else running.tag}, "pinned": pinned}


def register(commands: Parsers) -> None:
    text = "Which install runs and which is pinned for this machine config (read-only)"
    version = commands.add_parser("version", help=text, description=text, allow_abbrev=False)
    version.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data")
    text = ("Build one immutable install of a commit under ~/.local/share/task-loop/installs/<commit>/ from the checkout's Git "
            "objects (never pins)")
    install = commands.add_parser("install", help=text, description=text, allow_abbrev=False)
    install.add_argument("rev", metavar="REV", help="An annotated tag name or a full commit id")
    install.add_argument("--checkout", required=True, metavar="PATH", help="The checkout whose Git objects are read (no fetch)")
    text = ("Choose the install tl runs from its next start for this machine config (<config stem>.pin.toml beside it), or "
            "--clear the choice; never reads factory.db or Git")
    pin = commands.add_parser("pin", help=text, description=text, allow_abbrev=False)
    chosen = pin.add_mutually_exclusive_group(required=True)
    chosen.add_argument("rev", metavar="REV", nargs="?", help="A full commit id or a tag name recorded by a complete install")
    chosen.add_argument("--clear", action="store_true", help="Remove the pin: tl runs the install it is started from")


def installed_line(result: Installed) -> str:
    """The last line: a new install and how to pin it, or `already` naming the recorded and the given tag when they differ."""
    manifest = result.manifest
    if result.already:
        asked = "" if result.asked is None or result.asked == manifest.tag else f" (given as {result.asked})"
        return f"Installed: already {_named(manifest.commit, manifest.tag)}{asked} ({result.install})"
    return (f"Installed: {_named(manifest.commit, manifest.tag)}; not pinned (tl pin {manifest.tag or manifest.commit} runs it "
            "from the next start)")


def _say(text: str) -> None:
    print(text, flush=True)


def run_install(arguments: argparse.Namespace) -> int:
    """`tl install`: 0 installed or already, 1 refused, 3 unavailable (rerun is safe), 130 interrupted by Ctrl-C."""
    result = install_op.install(arguments.rev, arguments.checkout, cli_composition.install_ports(_say))
    match result:
        case Installed():
            print(installed_line(result))
            return 0
        case Refused(word=word, detail=detail):
            print(f"tl install: refused {word}: {detail}", file=sys.stderr)
            return 1
        case Unavailable(word=word, detail=detail):
            print(f"tl install: unavailable {word}: {detail}", file=sys.stderr)
            return 130 if word == "interrupted" else 3


def run(arguments: argparse.Namespace) -> int:
    """`tl version`: this process's prefix, the home's pin; always 0 (an invalid pin is reported, not refused)."""
    found = describe(Path(sys.prefix), Path.home(), arguments.config, LocalFiles())
    print(json.dumps(data(found)) if arguments.json_output else "\n".join(lines(found)))
    return 0


def drain(was: Was) -> str:
    """The drain procedure (plan sections 7 and 10), with the way back to the earlier choice when rounds still run: the
    new choice already applies to every new start, so the old version's commands need it back first."""
    match was:
        case Pin(commit=commit, tag=tag):
            back = f"tl pin {tag or commit}"
        case None:
            back = "tl pin --clear"
        case PinInvalid():
            return f"{EFFECT} The earlier pin was invalid: nothing to go back to."
    return f"{EFFECT} If rounds or attempts still run: {back} back, drain, then make this change again."


def _was(was: Was) -> str:
    match was:
        case None:
            return "none"
        case PinInvalid(detail=detail):
            return f"invalid ({detail})"
        case Pin(commit=commit, tag=tag):
            return _named(commit, tag)


def pinned_lines(result: Pinned | Cleared) -> list[str]:
    """`Pinned:` (or `Pinned: already`), what it replaced and the drain procedure; `Pin cleared` likewise."""
    match result:
        case Pinned(pin=pin, path=path, already=True):
            return [f"Pinned: already {_named(pin.commit, pin.tag)}, in {path}"]
        case Pinned(pin=pin, path=path, was=was):
            return [f"Pinned: {_named(pin.commit, pin.tag)}, in {path}", f"Was: {_was(was)}", drain(was)]
        case Cleared(was=None):
            return ["Pin cleared: already"]
        case Cleared(was=was):
            return [f"Pin cleared (was {_was(was)}); tl runs the install it is started from", drain(was)]


def run_pin(arguments: argparse.Namespace) -> int:
    """`tl pin REV` or `tl pin --clear`: 0 pinned, cleared or already, 1 refused, 3 unavailable (rerun is safe)."""
    files, home = LocalFiles(), Path.home()
    result = (pin_op.clear(files, home, arguments.config) if arguments.clear else
              pin_op.pin(files, home, arguments.config, arguments.rev, datetime.now(UTC)))
    match result:
        case Pinned() | Cleared():
            print("\n".join(pinned_lines(result)))
            return 0
        case pin_op.Refused(word=word, detail=detail):
            print(f"tl pin: refused {word}: {detail}", file=sys.stderr)
            return 1
        case pin_op.Unavailable(word=word, detail=detail):
            print(f"tl pin: unavailable {word}: {detail}", file=sys.stderr)
            return 3
