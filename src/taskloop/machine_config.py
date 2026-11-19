"""Machine configuration: the one owner of its keys, built-in defaults, precedence (flag > file > default) and refusals.

Pure: the file's text (None when the file is missing), the flags and the home directory in, values out. No environment
variable is read; `~` is expanded against the given home only.
"""

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

from taskloop.agents.config import configuration_error, resolve_agents
from taskloop.agents.settings import StepSettings
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, MAX_GIT_READ_SECONDS, MIN_GIT_READ_SECONDS
from taskloop.task import TaskInspectionError, TaskScope

type Source = Literal["flag", "file", "default"]
MIN_SECONDS: Final = 5
BACKLOG, BACKLOGS, UNKNOWN_KEY, TYPE = "backlog", "backlogs", "unknown_key", "type"  # repeated key and reason words
FILE: Final[Source] = "file"
type Refusal = Literal[
    "missing", "unreadable", "toml", "unknown_key", "type", "relative_path", "count", "interval", "backlog_missing", "binding_missing"
]


class Bound(StrEnum):
    """The keys of one `[backlogs.<key>]` table: the one vocabulary of a backlog's binding."""

    TRACKER_ROOT = "tracker_root"
    CHECKOUT = "checkout"
    LABEL = "label"


@dataclass(frozen=True)
class Setting[T]:
    value: T
    source: Source


@dataclass(frozen=True)
class Binding:
    """What the file binds one backlog to; each field is None where its table omits it."""

    tracker_root: Path | None = None
    checkout: Path | None = None
    label: str | None = None


@dataclass(frozen=True)
class Effective:
    db: Setting[Path]
    artifacts: Setting[Path]
    slots_root: Setting[Path]
    slot_count: Setting[int]
    round_seconds: Setting[int]  # `tl rounds start`: seconds from the end of one regular round to the next
    git_read_seconds: Setting[int]  # seconds a Git read (status, diff, ls-files, ...) may take before it is `unavailable:git`
    backlog: Setting[str | None]  # the file's default for `tl attempt show`; its explicit flag remains a separate input

    agents: StepSettings = field(default_factory=StepSettings)
    agent_sources: dict[str, str] = field(default_factory=dict)
    # backlog key -> its file binding
    backlogs: Mapping[str, Binding] = field(default_factory=lambda: MappingProxyType(dict[str, Binding]()))

    def pairs(self) -> tuple[tuple[str, Setting[Path] | Setting[int] | Setting[str | None] | Setting[str]], ...]:
        """Every key with its setting, in key order; then each binding's keys (always from the file), sorted by backlog."""
        keys: tuple[tuple[str, Setting[Path] | Setting[int] | Setting[str | None] | Setting[str]], ...] = (
            ("db", self.db), ("artifacts", self.artifacts), ("slots_root", self.slots_root), ("slot_count", self.slot_count),
            ("round_seconds", self.round_seconds), ("git_read_seconds", self.git_read_seconds), (BACKLOG, self.backlog))
        bound = tuple((f"{BACKLOGS}.{name}.{key}", Setting(value, FILE)) for name, binding in sorted(self.backlogs.items())
                      for key in Bound if (value := getattr(binding, key)) is not None)
        return keys + bound


KEYS: Final = tuple(field.name for field in fields(Effective) if field.name != "agent_sources")  # the file's only keys


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
        Setting(None, "default"),
    )


class _Refusal(Exception):
    def __init__(self, refused: ConfigRefused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


def _path(home: Path) -> Callable[[str, object], Path]:
    def checked(key: str, value: object) -> Path:
        if not isinstance(value, str):
            raise _Refusal(ConfigRefused(TYPE, key, f"{key} must be a path string"))
        path = home / value[2:] if value.startswith("~/") else home if value == "~" else Path(value)
        if not path.is_absolute():
            raise _Refusal(ConfigRefused("relative_path", key, f"{key} must be an absolute path: {value}"))
        return path

    return checked


def _integer(key: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Refusal(ConfigRefused(TYPE, key, f"{key} must be an integer"))
    return value


def _backlog(key: str, value: object) -> str:
    detail = f"{key} must be a nonempty string identifying a logical backlog"
    if not isinstance(value, str):
        raise _Refusal(ConfigRefused(TYPE, key, detail))
    try:
        return TaskScope(value).backlog
    except TaskInspectionError as error:
        raise _Refusal(ConfigRefused(TYPE, key, detail)) from error


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


def _label(key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Refusal(ConfigRefused(TYPE, key, f"{key} must be a nonempty string (the approval label)"))
    return value


def _bindings(table: object, home: Path) -> dict[str, Binding]:
    """`[backlogs.<key>]` tables: each key a backlog, each field one of `Bound`; anything else is refused."""
    if not isinstance(table, dict):
        raise _Refusal(ConfigRefused(TYPE, BACKLOGS, "backlogs must be a table of one table per backlog"))
    found: dict[str, Binding] = {}
    for name, each in table.items():
        key = _backlog(BACKLOGS, name)
        if not isinstance(each, dict):
            raise _Refusal(ConfigRefused(TYPE, f"{BACKLOGS}.{key}", f"{BACKLOGS}.{key} must be a table"))
        unknown = sorted(set(each) - set(Bound))
        if unknown:
            raise _Refusal(ConfigRefused(UNKNOWN_KEY, f"{BACKLOGS}.{key}.{unknown[0]}", f"Unknown keys: {', '.join(unknown)}"))
        path = _path(home)
        full = f"{BACKLOGS}.{key}."
        found[key] = Binding(
            path(full + Bound.TRACKER_ROOT, each[Bound.TRACKER_ROOT]) if Bound.TRACKER_ROOT in each else None,
            path(full + Bound.CHECKOUT, each[Bound.CHECKOUT]) if Bound.CHECKOUT in each else None,
            _label(full + Bound.LABEL, each[Bound.LABEL]) if Bound.LABEL in each else None,
        )
    return found


_seconds = _between(MIN_SECONDS)  # a rounds interval: whole seconds (the local check runs every 2 s between rounds)


def _chosen[T](key: str, table: dict[str, object], flag: object, default: Setting[T], check: Callable[[str, object], T]) -> Setting[T]:
    """Every given value is checked (the file's too, when a flag overrides it); the last given one wins."""
    chosen = default
    for source, value in ((FILE, table.get(key)), ("flag", flag)):
        if value is not None:
            chosen = Setting(check(key, value), FILE if source == FILE else "flag")
    return chosen


def resolve(text: str | None, flags: Flags, home: Path) -> Effective | ConfigRefused:
    """The file's text (None: no file, all defaults), then each key by precedence; the first refusal stops."""
    try:
        table = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as error:
        return ConfigRefused("toml", detail=str(error))
    unknown = sorted(set(table) - set(KEYS))
    if unknown:
        return ConfigRefused(UNKNOWN_KEY, unknown[0], f"Unknown keys: {', '.join(unknown)}")
    built, path = defaults(home), _path(home)
    try:
        agents, sources = resolve_agents(table.get("agents", {}), home)
    except (ValueError, OSError) as error:
        key, detail = configuration_error(error)
        return ConfigRefused(TYPE, key, detail)
    try:
        return Effective(
            _chosen("db", table, flags.db, built.db, path),
            _chosen("artifacts", table, flags.artifacts, built.artifacts, path),
            _chosen("slots_root", table, flags.slots_root, built.slots_root, path),
            _chosen("slot_count", table, flags.slot_count, built.slot_count, _count),
            _chosen("round_seconds", table, flags.round_seconds, built.round_seconds, _seconds),
            _chosen("git_read_seconds", table, flags.git_read_seconds, built.git_read_seconds,
                    _between(MIN_GIT_READ_SECONDS, MAX_GIT_READ_SECONDS)),
            _chosen(BACKLOG, table, None, built.backlog, _backlog),
            agents, sources, MappingProxyType(_bindings(table.get(BACKLOGS, {}), home)),
        )
    except _Refusal as refusal:
        return refusal.refused


def resolve_backlog(settings: Effective, flag: str | None) -> str | ConfigRefused:
    """The backlog a command works on: the flag, else the file's `backlog`, else refused (`attempt show` adds its own fallback)."""
    chosen = flag if flag is not None else settings.backlog.value
    return chosen if chosen is not None else ConfigRefused("backlog_missing", BACKLOG, "No backlog is given or configured")


def _bound(settings: Effective, backlog: str, key: Bound, flag: str | None) -> str | Path | ConfigRefused:
    """One binding value: the flag, else `backlogs.<backlog>.<key>` of the file, else refused naming the key."""
    if flag is not None:
        return flag
    value = getattr(settings.backlogs.get(backlog, Binding()), key)
    return value if value is not None else ConfigRefused("binding_missing", key, f"Backlog {backlog} has no {key} configured")


def resolve_tracker_root(settings: Effective, backlog: str, flag: str | None) -> str | ConfigRefused:
    found = _bound(settings, backlog, Bound.TRACKER_ROOT, flag)
    return found if isinstance(found, ConfigRefused) else str(found)


def resolve_checkout(settings: Effective, backlog: str, flag: str | None) -> Path | ConfigRefused:
    found = _bound(settings, backlog, Bound.CHECKOUT, flag)
    return found if isinstance(found, ConfigRefused) else Path(found)


def resolve_label(settings: Effective, backlog: str, flag: str | None) -> str | ConfigRefused:
    found = _bound(settings, backlog, Bound.LABEL, flag)
    return found if isinstance(found, ConfigRefused) else str(found)
