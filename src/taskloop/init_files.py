"""The files `tl init` writes into a checkout's working tree, and the one place that decides where each goes."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from taskloop.profile import DEFAULT_SETUP, DEFAULT_TARGET, PROFILE_PATH
from taskloop.workflow_read import DIRECTORY
from taskloop.workflow_starter import STARTER

Writer = Callable[[Path, str], None]  # creates the file and its folders; raises FileExistsError rather than overwrite

# setup is filled; checks and required stay empty, so a task is refused (no_required) until the owner names the checks
PROFILE_STARTER: Final = (
    json.dumps(
        {"setup": [list(argv) for argv in DEFAULT_SETUP], "checks": [], "required": [], "target": DEFAULT_TARGET, "land": "manual"},
        indent=2,
    )
    + "\n"
)


@dataclass(frozen=True)
class Scaffold:
    """Which files this run created and which it found and left unchanged."""

    created: tuple[Path, ...]
    kept: tuple[Path, ...]


def workflow_path(checkout: Path, name: str) -> Path:
    return checkout / f"{DIRECTORY}{name}.toml"


def scaffold(checkout: Path, name: str, write: Writer) -> Scaffold:
    """Write each absent file into the checkout's working tree, never over one: nothing is staged, committed or read from Git."""
    created: list[Path] = []
    kept: list[Path] = []
    for path, text in ((checkout / PROFILE_PATH, PROFILE_STARTER), (workflow_path(checkout, name), STARTER)):
        try:
            write(path, text)
        except FileExistsError:
            kept.append(path)
        else:
            created.append(path)
    return Scaffold(tuple(created), tuple(kept))


def create_new(path: Path, text: str) -> None:
    """The real writer: exclusive create, so a file that exists (or appears meanwhile) is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
