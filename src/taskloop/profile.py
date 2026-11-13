"""The repository profile `.task-loop.json`: its one reader, validator and the version rule (D11).

Strict and minimal: `setup` (ordered argv lists that prepare a slot; `just install` when the key is absent), `checks`
(name, argv, timeout seconds), `required` (check names), `target` (the land branch, `main` when absent) and `land`
(`manual` when absent: a person lands a passed task; `auto`:
each round lands one, tl-8bh9.14.136; read from the target ref, like `required`). Unknown keys,
duplicate names and oversized content are refused; there is no reader of any older key. The file is always read from
Git at a commit through the `ProfileFiles` port, never from a working tree. `resolve` applies GitHub's model: the
commands (`setup`, `checks`) come from the commit under test, like a `push`/`pull_request` workflow; `required` and
`target` come from the target ref, like branch protection, so a commit cannot drop a required check. Typed values in,
typed values out; no execution of anything the profile names.
"""

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Literal, Protocol

PROFILE_PATH: Final = ".task-loop.json"
MAX_BYTES: Final = 64 * 1024
MAX_CHECKS: Final = 32  # also the most setup commands and required names
MAX_ARGV: Final = 64
MAX_ARG: Final = 4096
MAX_NAME: Final = 64
MAX_BRANCH: Final = 255
MAX_SHOWN: Final = 64
NAME_CHARS: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
BRANCH_BAD: Final = frozenset("~^:?*[\\")  # git check-ref-format
MAX_TIMEOUT: Final = 86400
DEFAULT_SETUP: Final = (("just", "install"),)
DEFAULT_TARGET: Final = "main"
KEYS: Final = ("setup", "checks", "required", "target", "land")
CHECK_KEYS: Final = ("name", "argv", "timeout")

type Reason = Literal[
    "missing", "no_commit", "not_json", "not_object", "unknown_key", "bad_value", "too_large", "duplicate_check",
    "required_undefined", "not_a_file",
]
type Side = Literal["commit", "target"]
type Argv = tuple[str, ...]


class LandMode(StrEnum):
    """Who lands a task whose checks passed: a person (`manual`, the default) or the factory's own round (`auto`)."""

    MANUAL = "manual"
    AUTO = "auto"


@dataclass(frozen=True)
class Check:
    name: str
    argv: Argv
    timeout: int  # seconds


@dataclass(frozen=True)
class Profile:
    """One commit's valid profile."""

    setup: tuple[Argv, ...]
    checks: tuple[Check, ...]
    required: tuple[str, ...]
    target: str
    land: LandMode = LandMode.MANUAL


@dataclass(frozen=True)
class Resolved:
    """What a step uses: `setup` and `checks` from the commit under test, `required` and `target` from the target ref."""

    setup: tuple[Argv, ...]
    checks: tuple[Check, ...]
    required: tuple[str, ...]
    target: str


@dataclass(frozen=True)
class Refused:
    """A fixed reason word; `side` names whose profile (the commit's or the target's), `key` the offending key path."""

    reason: Reason
    key: str = ""
    detail: str = ""
    side: Side = "commit"


@dataclass(frozen=True)
class Unavailable:
    """Git could not be read: no verdict on the profile; reading again is safe."""

    detail: str


@dataclass(frozen=True)
class NoCommit:
    """The revision names no commit."""


@dataclass(frozen=True)
class NotAFile:
    """The path is in the commit's tree as a symlink, submodule or other non-regular entry: never read as the profile."""

    mode: str


class ProfileFiles(Protocol):
    def blob(self, commit: str, path: str) -> bytes | NoCommit | NotAFile | Unavailable | None:
        """The regular file's bytes at `commit` (None: no such path there), never the working tree's."""
        ...


class _Refusal(Exception):
    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


def _refuse(reason: Reason, key: str, detail: str) -> _Refusal:
    return _Refusal(Refused(reason, key, detail))


def shown(text: str) -> str:
    """Text safe to print in a refusal: as is when short printable ASCII, else escaped and shortened."""
    if len(text) <= MAX_SHOWN and text.isascii() and text.isprintable():
        return text
    return ascii(text[:MAX_SHOWN])


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A JSON object whose keys appear once; a repeated key is ambiguous, so the text is not accepted."""
    table: dict[str, object] = {}
    for key, value in pairs:
        if key in table:
            raise ValueError(f"Duplicate key {key!r}")
        table[key] = value
    return table


def _constant(name: str) -> object:
    raise ValueError(f"{name} is not JSON")


def _items(key: str, value: object, cap: int) -> list[object]:
    if not isinstance(value, list):
        raise _refuse("bad_value", key, f"{key} must be a list")
    if len(value) > cap:
        raise _refuse("too_large", key, f"{key} has more than {cap} items")
    return list(value)


def _word(key: str, value: object, cap: int) -> str:
    """A non-empty name without whitespace or control characters, at most `cap` characters."""
    if not isinstance(value, str) or not value or not value.isprintable() or any(each.isspace() for each in value):
        raise _refuse("bad_value", key, f"{key} must be a non-empty word without whitespace")
    if len(value) > cap:
        raise _refuse("too_large", key, f"{key} is longer than {cap} characters")
    return value


def _name(key: str, value: object) -> str:
    """A check name: `[A-Za-z0-9._-]`, not starting with `.` or `-`, at most MAX_NAME characters."""
    if not isinstance(value, str) or not value or not set(value) <= NAME_CHARS or value[0] in ".-":
        raise _refuse("bad_value", key, f"{key} must be letters, digits, '.', '_' or '-', not starting with '.' or '-'")
    if len(value) > MAX_NAME:
        raise _refuse("too_large", key, f"{key} is longer than {MAX_NAME} characters")
    return value


def _branch(key: str, value: object) -> str:
    """A branch name by `git check-ref-format`'s rules, so it is never an option or a path trick."""
    text = _word(key, value, MAX_BRANCH)
    parts = text.split("/")
    if (text[0] in "-/" or text[-1] in "/." or text == "@" or "@{" in text or ".." in text or "//" in text
            or BRANCH_BAD & set(text) or any(each.startswith(".") or each.endswith(".lock") for each in parts)):
        raise _refuse("bad_value", key, f"{key} is not a valid branch name")
    return text


def _land(key: str, value: object) -> LandMode:
    try:
        return LandMode(value)
    except ValueError:
        raise _refuse("bad_value", key, f"{key} must be one of: {', '.join(each.value for each in LandMode)}") from None


def _argv(key: str, value: object) -> Argv:
    """A non-empty argv of non-empty printable strings (no control character or surrogate), the program not blank,
    each at most MAX_ARG characters."""
    items = _items(key, value, MAX_ARGV)
    if not items:
        raise _refuse("bad_value", key, f"{key} must name a program")
    argv: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip(" " if index else None) or not item.isprintable():
            raise _refuse("bad_value", f"{key}[{index}]", f"{key}[{index}] must be a non-empty printable string")
        if len(item) > MAX_ARG:
            raise _refuse("too_large", f"{key}[{index}]", f"{key}[{index}] is longer than {MAX_ARG} characters")
        argv.append(item)
    return tuple(argv)


def _timeout(key: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_TIMEOUT:
        raise _refuse("bad_value", key, f"{key} must be whole seconds from 1 to {MAX_TIMEOUT}")
    return value


def _check(key: str, value: object) -> Check:
    if not isinstance(value, dict):
        raise _refuse("bad_value", key, f"{key} must be an object")
    unknown = sorted(shown(str(each)) for each in value if each not in CHECK_KEYS)
    if unknown:
        raise _refuse("unknown_key", f"{key}.{unknown[0]}", f"Unknown keys in {key}: {', '.join(unknown)}")
    absent = [each for each in CHECK_KEYS if each not in value]
    if absent:
        raise _refuse("bad_value", f"{key}.{absent[0]}", f"{key} needs {', '.join(CHECK_KEYS)}")
    return Check(_name(f"{key}.name", value["name"]), _argv(f"{key}.argv", value["argv"]),
                 _timeout(f"{key}.timeout", value["timeout"]))


def _checks(value: object) -> tuple[Check, ...]:
    checks = tuple(_check(f"checks[{index}]", each) for index, each in enumerate(_items("checks", value, MAX_CHECKS)))
    names = [check.name for check in checks]
    repeated = next((name for index, name in enumerate(names) if name in names[:index]), None)
    if repeated is not None:
        raise _refuse("duplicate_check", "checks", f"Check {repeated!r} is defined more than once")
    return checks


def _required(value: object) -> tuple[str, ...]:
    names = [_name(f"required[{index}]", each) for index, each in enumerate(_items("required", value, MAX_CHECKS))]
    if len(set(names)) != len(names):
        raise _refuse("bad_value", "required", "required names a check more than once")
    return tuple(names)


def _table(data: bytes) -> dict[str, object]:
    if len(data) > MAX_BYTES:
        raise _refuse("too_large", "", f"{PROFILE_PATH} is larger than {MAX_BYTES} bytes")
    try:
        value: object = json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _refuse("not_json", "", str(error)) from error
    if not isinstance(value, dict):
        raise _refuse("not_object", "", f"{PROFILE_PATH} must be a JSON object")
    table = {str(key): each for key, each in value.items()}
    unknown = sorted(shown(each) for each in set(table) - set(KEYS))
    if unknown:
        raise _refuse("unknown_key", unknown[0], f"Unknown keys: {', '.join(unknown)}")
    return table


def parse(data: bytes) -> Profile | Refused:
    """The profile's bytes, strictly validated; the first refusal stops. Absent keys take their defaults."""
    try:
        table = _table(data)
        setup = DEFAULT_SETUP if "setup" not in table else tuple(
            _argv(f"setup[{index}]", each) for index, each in enumerate(_items("setup", table["setup"], MAX_CHECKS))
        )
        checks = _checks(table.get("checks", []))
        required = _required(table.get("required", []))
        target = DEFAULT_TARGET if "target" not in table else _branch("target", table["target"])
        land = LandMode.MANUAL if "land" not in table else _land("land", table["land"])
    except _Refusal as refusal:
        return refusal.refused
    return Profile(setup, checks, required, target, land)


def read_profile(files: ProfileFiles, commit: str) -> Profile | Refused | Unavailable:
    """The profile in Git at `commit`: `missing` when that commit has no profile file (no default profile: a default
    applies only to a key absent from a profile that exists), `no_commit` when the revision names no commit,
    `not_a_file` when the path is a symlink or submodule there."""
    found = files.blob(commit, PROFILE_PATH)
    match found:
        case Unavailable():
            return found
        case NoCommit():
            return Refused("no_commit", detail=f"{shown(commit)} names no commit")
        case NotAFile(mode=mode):
            return Refused("not_a_file", detail=f"{PROFILE_PATH} at {shown(commit)} is not a regular file (mode {mode})")
        case None:
            return Refused("missing", detail=f"No {PROFILE_PATH} at {shown(commit)}")
        case bytes():
            return parse(found)


def _undefined(required: tuple[str, ...], checks: tuple[Check, ...]) -> list[str]:
    defined = {check.name for check in checks}
    return [name for name in required if name not in defined]


def resolve(files: ProfileFiles, commit: str, target_ref: str) -> Resolved | Refused | Unavailable:
    """`setup` and `checks` from `commit`'s profile, `required` and `target` from `target_ref`'s. A required name either
    profile's checks do not define is `required_undefined` (the target's own first), as a required GitHub check that
    never reports blocks the merge."""
    at = read_profile(files, commit)
    if not isinstance(at, Profile):
        return at if isinstance(at, Unavailable) else replace(at, side="commit")
    base = read_profile(files, target_ref)
    if not isinstance(base, Profile):
        return base if isinstance(base, Unavailable) else replace(base, side="target")
    sides: tuple[tuple[Side, str, tuple[Check, ...]], ...] = (("target", target_ref, base.checks), ("commit", commit, at.checks))
    for side, where, checks in sides:
        undefined = _undefined(base.required, checks)
        if undefined:
            return Refused("required_undefined", "required", f"Required but not defined at {shown(where)}: {', '.join(undefined)}", side)
    return Resolved(at.setup, at.checks, base.required, base.target)
