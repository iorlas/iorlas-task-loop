"""The owner pin: `<config stem>.pin.toml` beside the machine config in use (tl-8bh9.8.3 section 4.4).

Only `commit` decides; `tag` is display only. Read once by `start` before the CLI and by `tl version`; written and cleared
only by the owner's pin operation, atomically. Imports the standard library, `installs` and the machine config's fixed
location (its one owner, itself standard library only).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from taskloop.installs import Reads, Writes, atomic_write, basic_string, is_commit, is_tag, parse_table, utc_text
from taskloop.machine_config import config_file


@dataclass(frozen=True)
class Pin:
    commit: str
    tag: str | None
    pinned_at: str


@dataclass(frozen=True)
class PinInvalid:
    detail: str


def pin_path(config: str | None, home: Path) -> Path | None:
    """`<folder>/<stem>.pin.toml` of the machine config in use: `--config FILE` (made absolute as the config reader does),
    else the fixed `~/.config/task-loop/config.toml`. Two configs in one folder have two pins. None when `--config` names
    no file (empty, or a path without a name such as `/`): such a config has no pin file."""
    path = config_file(home) if config is None else Path(config).absolute()
    return None if config == "" or not path.name else path.with_name(f"{path.stem}.pin.toml")


def nameless(config: str | None) -> PinInvalid:
    """Why a config path without a name has no pin."""
    return PinInvalid(f"--config {config!r} names no file, so it has no pin file")


def read(files: Reads, path: Path) -> Pin | PinInvalid | None:
    """The pin, None when there is no file, or why the file is not a pin."""
    try:
        text = files.read_text(path)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        return PinInvalid(f"unreadable: {type(error).__name__}")
    found = parse_table(text, ("commit", "pinned_at"), ("tag",))
    if isinstance(found, str):
        return PinInvalid(found)
    if not is_commit(found["commit"]):
        return PinInvalid(f"commit {found['commit']!r} is not a full commit id")
    return Pin(found["commit"], found.get("tag"), found["pinned_at"])


def write(files: Writes, path: Path, commit: str, tag: str | None, now: datetime) -> Pin:
    """Record the pin atomically (an OSError leaves the old file); ValueError for a value it does not write."""
    if not is_commit(commit) or (tag is not None and not is_tag(tag)):
        raise ValueError(f"not a pin: {commit!r} {tag!r}")
    pin = Pin(commit, tag, utc_text(now))
    tag_line = "" if tag is None else f"tag = {basic_string(tag)}\n"
    atomic_write(files, path, f"format = 1\ncommit = {basic_string(commit)}\n{tag_line}pinned_at = {basic_string(pin.pinned_at)}\n")
    return pin


def clear(files: Writes, path: Path) -> bool:
    """Remove the pin file; False when there was none."""
    if not files.remove(path):
        return False
    files.sync_folder(path.parent)
    return True
