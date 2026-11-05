"""Reading a decoded JSON value without trusting its shape: what a vendor CLI or a state file may send is `Json`; these narrow it."""

from delegate.contracts.json_types import Json


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


def text(x: Json) -> str:
    """`x` as text: a string as is, nothing as "", anything else as Python prints it."""
    return x if isinstance(x, str) else "" if x is None else str(x)
