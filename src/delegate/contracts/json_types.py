"""The shape of a decoded JSON value: what delegate reads from a vendor CLI, its config files and its own state, before a record narrows it.

Read-only containers (Mapping, Sequence) so a `list[str]` or a `dict[str, float]` is a Json without a copy; `isinstance(x, dict)` / `list`
narrows."""

from collections.abc import Mapping, Sequence

type Json = Mapping[str, Json] | Sequence[Json] | str | int | float | bool | None


def obj(x: Json) -> dict[str, Json]:
    """`x` when it is an object, else an empty one: a config file of the wrong shape reads as having none of the keys."""
    return x if isinstance(x, dict) else {}


def arr(x: Json) -> list[Json]:
    """`x` when it is an array, else an empty list."""
    return x if isinstance(x, list) else []


def as_str(x: Json, default: str = "") -> str:
    """`x` when it is a string, else `default`."""
    return x if isinstance(x, str) else default


def as_num(x: Json) -> float | None:
    """`x` when it is a number (a bool is not one), else None. An int stays an int: the bytes read are the bytes written back."""
    return x if isinstance(x, int | float) and not isinstance(x, bool) else None


def as_opt_str(x: Json) -> str | None:
    """`x` when it is a string, else None."""
    return x if isinstance(x, str) else None


def as_strs(x: Json) -> list[str]:
    """The strings of `x` when it is an array, else an empty list."""
    return [e for e in x if isinstance(e, str)] if isinstance(x, list) else []


def as_opt_obj(x: Json) -> dict[str, Json] | None:
    """`x` when it is an object, else None."""
    return x if isinstance(x, dict) else None


def as_opt_int(x: Json) -> int | None:
    """`x` when it is an int (a bool is not one), else None."""
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def as_opt_bool(x: Json) -> bool | None:
    """`x` when it is a bool, else None."""
    return x if isinstance(x, bool) else None
