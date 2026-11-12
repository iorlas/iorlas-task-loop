"""The install commands' surface; built so far: `tl version [--json]` and `tl install REV --checkout PATH`
(tl-8bh9.8.3 sections 6.1 and 6.3).

`tl version` is read-only: this process's install (`sys.prefix` and the manifest beside it, through `installs.state`) and
the pin of the machine config in use; no factory.db, no lock, no listing of the installs. `tl install` runs the one
operation `install_op.install` over `cli_composition.install_ports` and prints its progress as it goes; text only.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from taskloop import cli_composition, install_op, pin_file
from taskloop.install_op import Installed, Refused, Unavailable
from taskloop.installs import LocalFiles, Manifest, Reads, installs_root, state
from taskloop.pin_file import Pin, PinInvalid

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
    resolved, root = prefix.resolve(), installs_root(home).resolve()
    install = resolved.parent
    found = state(files, root, install.name) if resolved.name == "venv" and install.parent == root else None
    path = pin_file.pin_path(config, home)
    pinned = pin_file.nameless(config) if path is None else pin_file.read(files, path)
    return Version(resolved, found.manifest if found is not None else None, path, pinned)


def _named(commit: str, tag: str | None) -> str:
    return commit[:12] if tag is None else f"{commit[:12]} {tag}"


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
