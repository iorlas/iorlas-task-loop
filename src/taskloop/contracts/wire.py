"""The base of every record: a frozen pydantic model that refuses unknown keys, plus the two calls that give it its wire form.

`V` (class attribute) is a record's wire version: `dump` writes it first as `v` (a nested record carries none), `load` refuses any
other with StaleRecord and never migrates. A union of records is discriminated on the `kind` field each member declares. A field
renamed on the wire (`in` is a keyword) says so with `Field(alias="in")`. `load` is strict: no coercion (a string is not a number,
a bool is not an int); a violation raises pydantic's ValidationError, a ValueError like StaleRecord.
"""
import functools
import json
from typing import Annotated, Any, ClassVar, get_args

from pydantic import BaseModel, ConfigDict, PlainSerializer, PlainValidator, TypeAdapter

from taskloop.contracts.ids import RunId


class StaleRecord(ValueError):
    """The data carries another `v` than the class: the record is treated as absent, never migrated."""

    def __init__(self, name: str, found: object, want: int) -> None:
        super().__init__(f"{name}: v={found!r}, this code reads v={int(want)}")
        self.found = found
        self.want = want


class Rec(BaseModel):
    """A record: keyword-only, frozen, no unknown keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)
    V: ClassVar[int | None] = None


def _run_id(value: Any) -> RunId:
    return value if isinstance(value, RunId) else RunId.parse(value)


RunIdWire = Annotated[RunId, PlainValidator(_run_id), PlainSerializer(RunId.to_wire, return_type=str)]
"""A RunId field: its string on the wire."""
SortedSet = Annotated[set[str], PlainSerializer(sorted, return_type=list[str], when_used="json")]
"""A set of strings: written as a sorted array."""


@functools.cache
def _adapter(tp: Any) -> TypeAdapter[Any]:
    return TypeAdapter(tp)


def _version(tp: Any) -> int | None:
    """The `V` of a record class, or the one `V` of every member of a union (`Annotated[A | B, Field(discriminator=...)]`)."""
    if isinstance(tp, type):
        return tp.V if issubclass(tp, Rec) else None
    seen = {_version(m) for m in get_args(get_args(tp)[0])}
    return seen.pop() if len(seen) == 1 else None


def load(tp: Any, data: Any) -> Any:
    """The record of class (or union) `tp` from a dict; StaleRecord when its `v` is not the class's."""
    want = _version(tp)
    if want is not None and isinstance(data, dict):
        if data.get("v") != want:
            raise StaleRecord(getattr(tp, "__name__", "record"), data.get("v"), want)
        data = {k: x for k, x in data.items() if k != "v"}
    return _adapter(tp).validate_json(json.dumps(data), strict=True)


def dump(rec: Any) -> dict[str, Any]:
    """The record (a Rec) as a JSON-able dict: `v` first when the class has one, then its fields in declaration order."""
    body = rec.model_dump(mode="json")
    return body if rec.V is None else {"v": rec.V, **body}
