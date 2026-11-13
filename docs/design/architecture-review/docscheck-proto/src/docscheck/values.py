"""Shared value types: the JSON shape of frontmatter and a finding."""

import datetime
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


@dataclass(frozen=True, order=True)
class Finding:
    """One problem, stable to print: `<doc>: <field>: <code>: <message>`. `waivable` ids drop out through waivers."""

    doc: str
    field: str
    code: str
    message: str

    @property
    def key(self) -> str:
        """The id a waiver names: doc, field, code and a short digest of the message (one finding per fact)."""
        return f"{self.doc}:{self.field}:{self.code}@{hashlib.sha1(self.message.encode()).hexdigest()[:6]}"

    def line(self, *, keys: bool = False) -> str:
        text = f"{self.doc}: {self.field}: {self.code}: {self.message}"
        return f"{text}   [{self.key}]" if keys else text


def plain(value: object) -> Json:
    """A ruamel round-trip value as plain JSON types (dates become ISO strings)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def as_map(value: Json) -> dict[str, Json]:
    return value if isinstance(value, dict) else {}


def as_list(value: Json) -> list[Json]:
    return value if isinstance(value, list) else []


def as_str(value: Json) -> str:
    return value if isinstance(value, str) else ""
