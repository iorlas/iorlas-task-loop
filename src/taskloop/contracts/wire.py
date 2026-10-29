"""The base of every record: a frozen msgspec Struct that refuses unknown keys, plus the two calls that give it its wire form.

`V` (class attribute) is a record's wire version: `dump` writes it first as `v` (a nested record carries none), `load` refuses any
other with StaleRecord and never migrates. A union of records is tagged on `kind` (`Tagged`, each member says `tag="..."`). A field
renamed on the wire (`in` is a keyword) says so with `msgspec.field(name="in")`. `load` is strict: no coercion (a string is not a
number, a bool is not an int); a violation raises msgspec.ValidationError, a ValueError like StaleRecord.
"""
from typing import Any, ClassVar, dataclass_transform, get_args

import msgspec


class StaleRecord(ValueError):
    """The data carries another `v` than the class: the record is treated as absent, never migrated."""

    def __init__(self, name: str, found: object, want: int) -> None:
        super().__init__(f"{name}: v={found!r}, this code reads v={int(want)}")
        self.found = found
        self.want = want


@dataclass_transform(frozen_default=True, kw_only_default=True)
class _RecordMeta(type(msgspec.Struct)):
    """The config of every record: keyword-only, frozen, no unknown keys. msgspec applies `kw_only` to the class that sets it, not to its
    subclasses (a required field could not follow a default one); the transform tells the type checker the same defaults."""

    def __new__(mcs, name: str, bases: tuple[type, ...], ns: dict[str, Any], **config: Any) -> Any:
        config.setdefault("kw_only", True)
        config.setdefault("frozen", True)
        config.setdefault("forbid_unknown_fields", True)
        return super().__new__(mcs, name, bases, ns, **config)


class Rec(msgspec.Struct, metaclass=_RecordMeta):
    """A record: keyword-only, frozen, no unknown keys."""

    V: ClassVar[int | None] = None

    def replace(self, **changes: Any) -> Any:
        return msgspec.structs.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """The fields as a JSON-able dict (no `v`): nested records, enums and sets in their wire form."""
        return msgspec.to_builtins(self, enc_hook=_enc)


class Tagged(Rec, tag_field="kind"):
    """The base of a union's members: each says `tag="<kind>"` and reads it back as `kind`."""

    @property
    def kind(self) -> str:
        return type(self).__struct_config__.tag  # type: ignore[return-value]


def names(cls: type[Rec]) -> tuple[str, ...]:
    """The field names of a record class, in declaration order."""
    return tuple(f.name for f in msgspec.structs.fields(cls))


def _enc(obj: Any) -> Any:
    return obj.to_wire()  # RunId


def _dec(tp: type, obj: Any) -> Any:
    return tp.from_wire(obj)


def _version(tp: Any) -> int | None:
    """The `V` of a record class, or the one `V` of every member of a union."""
    seen = {m.V for m in (get_args(tp) or (tp,)) if isinstance(m, type) and issubclass(m, Rec)}
    return seen.pop() if len(seen) == 1 else None


def load(tp: Any, data: Any) -> Any:
    """The record of class (or union) `tp` from JSON text, bytes or a dict; StaleRecord when its `v` is not the class's."""
    body = msgspec.json.decode(data) if isinstance(data, (bytes, str)) else data
    want = _version(tp)
    if want is not None and isinstance(body, dict):
        if body.get("v") != want:
            raise StaleRecord(getattr(tp, "__name__", "record"), body.get("v"), want)
        body = {k: x for k, x in body.items() if k != "v"}
    return msgspec.convert(body, tp, dec_hook=_dec)


def dump(rec: Any) -> dict[str, Any]:
    """The record as a JSON-able dict: `v` first when the class has one, then its fields in declaration order."""
    return rec.to_dict() if rec.V is None else {"v": rec.V, **rec.to_dict()}
