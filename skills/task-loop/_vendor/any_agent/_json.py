"""Reading a decoded JSON value without trusting its shape, and the two record decorators the package uses.

What a vendor CLI prints is `Json`; these narrow it. A `record` is frozen, a `mutable` is filled in as a run goes; both are
keyword-only and slotted.
"""

import dataclasses
import typing
from collections.abc import Mapping, Sequence

type Json = Mapping[str, Json] | Sequence[Json] | str | int | float | bool | None


@typing.dataclass_transform(kw_only_default=True, frozen_default=True)
def record[T](cls: type[T]) -> type[T]:
    """A frozen, keyword-only, slotted dataclass."""
    return dataclasses.dataclass(frozen=True, kw_only=True, slots=True)(cls)


@typing.dataclass_transform(kw_only_default=True)
def mutable[T](cls: type[T]) -> type[T]:
    """A record a process fills in as it goes: a keyword-only, slotted dataclass."""
    return dataclasses.dataclass(kw_only=True, slots=True)(cls)


def obj(x: Json) -> dict[str, Json]:
    """`x` when it is a JSON object, else an empty one."""
    return x if isinstance(x, dict) else {}


def objs(x: Json) -> list[dict[str, Json]]:
    """The JSON objects among the items of `x` (a list), else nothing."""
    return [b for b in x if isinstance(b, dict)] if isinstance(x, list) else []


def container(x: Json) -> Json:
    """`x` when it is a JSON object or array, else None."""
    return x if isinstance(x, dict) else x if isinstance(x, list) else None


def num(x: Json) -> int | float:
    """`x or 0` for a count a vendor may omit or send as null."""
    return x if isinstance(x, int | float) and x else 0


def opt_int(x: Json) -> int | None:
    """`x` when it is a whole number, else None."""
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def opt_str(x: Json) -> str | None:
    """`x` when it is a string, else None."""
    return x if isinstance(x, str) else None


def text(x: object) -> str:
    """`x` as text: a string as is, nothing as "", anything else as Python prints it."""
    return x if isinstance(x, str) else "" if x is None else str(x)
