"""Machine configuration: the one owner of its keys, built-in defaults, precedence (flag > file > default) and refusals.

Pure: the file's text (None when the file is missing), the flags and the home directory in, values out. No environment
variable is read; `~` is expanded against the given home only. Locations stay out of `~/.config/task-loop/` itself: that
folder is the baseline factory's live home on the owner's machine.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final, Literal

from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS

type Source = Literal["flag", "file", "default"]
MIN_SECONDS: Final = 5
MIN_GIT_READ_SECONDS: Final = 30
MAX_GIT_READ_SECONDS: Final = 86400  # a day; a larger value overflows the process timeout
type Refusal = Literal["missing", "unreadable", "toml", "unknown_key", "type", "relative_path", "count", "interval"]


@dataclass(frozen=True)
class Setting[T]:
    value: T
    source: Source


@dataclass(frozen=True)
class Effective:
    db: Setting[Path]
    artifacts: Setting[Path]
    slots_root: Setting[Path]
    slot_count: Setting[int]
    round_seconds: Setting[int]  # `tl step rounds`: seconds from the end of one regular round to the next
    git_read_seconds: Setting[int]  # seconds a Git read (status, diff, ls-files, ...) may take before it is `unavailable:git`

    def pairs(self) -> tuple[tuple[str, Setting[Path] | Setting[int]], ...]:
        """Every key with its setting, in key order."""
        return (("db", self.db), ("artifacts", self.artifacts), ("slots_root", self.slots_root), ("slot_count", self.slot_count),
                ("round_seconds", self.round_seconds), ("git_read_seconds", self.git_read_seconds))


KEYS: Final = tuple(field.name for field in fields(Effective))  # the file's only keys


@dataclass(frozen=True)
class Flags:
    """Command-line overrides; None where the command line names none."""

    db: str | None = None
    artifacts: str | None = None
    slots_root: str | None = None
    slot_count: int | None = None
    round_seconds: int | None = None
    git_read_seconds: int | None = None


@dataclass(frozen=True)
class Loaded:
    path: Path
    exists: bool
    settings: Effective


@dataclass(frozen=True)
class ConfigRefused:
    reason: Refusal
    key: str = ""
    detail: str = ""


def config_file(home: Path) -> Path:
    """The fixed machine config location; `--config FILE` replaces it."""
    return home / ".config" / "task-loop" / "config.toml"


def defaults(home: Path) -> Effective:
    """The one table of built-in defaults: disposable state under XDG "state", kept slots under XDG "data"."""
    state = home / ".local" / "state" / "task-loop"
    return Effective(
        Setting(state / "factory.db", "default"),
        Setting(state / "artifacts", "default"),
        Setting(home / ".local" / "share" / "task-loop" / "slots", "default"),
        Setting(1, "default"),
        Setting(60, "default"),
        Setting(DEFAULT_GIT_READ_SECONDS, "default"),
    )


class _Refusal(Exception):
    def __init__(self, refused: ConfigRefused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


def _path(home: Path) -> Callable[[str, object], Path]:
    def checked(key: str, value: object) -> Path:
        if not isinstance(value, str):
            raise _Refusal(ConfigRefused("type", key, f"{key} must be a path string"))
        path = home / value[2:] if value.startswith("~/") else home if value == "~" else Path(value)
        if not path.is_absolute():
            raise _Refusal(ConfigRefused("relative_path", key, f"{key} must be an absolute path: {value}"))
        return path

    return checked


def _integer(key: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Refusal(ConfigRefused("type", key, f"{key} must be an integer"))
    return value


def _count(key: str, value: object) -> int:
    if _integer(key, value) < 1:
        raise _Refusal(ConfigRefused("count", key, f"{key} must be at least 1"))
    return _integer(key, value)


def _between(minimum: int, maximum: int | None = None) -> Callable[[str, object], int]:
    def checked(key: str, value: object) -> int:
        number = _integer(key, value)
        if number < minimum or (maximum is not None and number > maximum):
            bound = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            raise _Refusal(ConfigRefused("interval", key, f"{key} must be {bound} seconds"))
        return number

    return checked


_seconds = _between(MIN_SECONDS)  # a rounds interval: whole seconds (the local check runs every 2 s between rounds)


def _chosen[T](key: str, table: dict[str, object], flag: object, default: Setting[T], check: Callable[[str, object], T]) -> Setting[T]:
    """Every given value is checked (the file's too, when a flag overrides it); the last given one wins."""
    chosen = default
    for source, value in (("file", table.get(key)), ("flag", flag)):
        if value is not None:
            chosen = Setting(check(key, value), "file" if source == "file" else "flag")
    return chosen


def resolve(text: str | None, flags: Flags, home: Path) -> Effective | ConfigRefused:
    """The file's text (None: no file, all defaults), then each key by precedence; the first refusal stops."""
    try:
        table = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as error:
        return ConfigRefused("toml", detail=str(error))
    unknown = sorted(set(table) - set(KEYS))
    if unknown:
        return ConfigRefused("unknown_key", unknown[0], f"Unknown keys: {', '.join(unknown)}")
    built, path = defaults(home), _path(home)
    try:
        return Effective(
            _chosen("db", table, flags.db, built.db, path),
            _chosen("artifacts", table, flags.artifacts, built.artifacts, path),
            _chosen("slots_root", table, flags.slots_root, built.slots_root, path),
            _chosen("slot_count", table, flags.slot_count, built.slot_count, _count),
            _chosen("round_seconds", table, flags.round_seconds, built.round_seconds, _seconds),
            _chosen("git_read_seconds", table, flags.git_read_seconds, built.git_read_seconds,
                    _between(MIN_GIT_READ_SECONDS, MAX_GIT_READ_SECONDS)),
        )
    except _Refusal as refusal:
        return refusal.refused
