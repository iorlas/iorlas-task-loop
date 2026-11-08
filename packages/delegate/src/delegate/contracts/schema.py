"""JSON Schema from a record class, and its strict-mode rewrite.

`of(cls)` is the contract form: an object with `additionalProperties: false`, every field without a default in `required`, an
optional (defaulted) field left out of it. `strict(schema)` is the wire form OpenAI-style strict structured output takes: every
property required, a field the contract left optional may be null. A field's description is `field(metadata={"doc": ...})`.
"""

import copy
import dataclasses
import enum
import types
from typing import Literal, Union, get_args, get_origin

from delegate.contracts.codec import Absent, plan
from delegate.contracts.json_types import Json

SCALARS: dict[object, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def of(cls: type) -> dict[str, Json]:
    """The contract schema of a dataclass."""
    fields = {f.name: f for f in dataclasses.fields(cls)}
    props: dict[str, Json] = {}
    required: list[Json] = []
    version, kind = getattr(cls, "V", None), getattr(cls, "KIND", None)
    if version is not None:
        props["v"] = {"type": "integer", "enum": [version]}
        required.append("v")
    if kind is not None:
        tag = getattr(cls, "TAG", "kind")
        props[tag] = {"type": "string", "enum": [kind]}
        required.append(tag)
    for p in plan(cls):
        node = _hint(p.hint)
        doc = fields[p.attr].metadata.get("doc")
        if doc:
            node = {**node, "description": doc}
        props[p.wire] = node
        if p.required:
            required.append(p.wire)
    return {"type": "object", "additionalProperties": False, "required": required, "properties": props}


def _hint(h: object) -> dict[str, Json]:
    if h is Json or h is object:
        return {}
    sup = getattr(h, "__supertype__", None)
    if sup is not None:
        return _hint(sup)
    origin = get_origin(h)
    if origin is None:
        return _hint_plain(h)
    return _hint_generic(h, origin, get_args(h))


def _hint_plain(h: object) -> dict[str, Json]:
    if h in SCALARS:
        return {"type": SCALARS[h]}
    if hasattr(h, "to_wire"):  # RunId, Version: a string on the wire
        return {"type": "string"}
    if isinstance(h, type) and issubclass(h, enum.Enum):
        members: list[Json] = [m.value for m in h]
        return {"type": "string", "enum": members}
    if isinstance(h, type) and dataclasses.is_dataclass(h):
        return of(h)
    raise TypeError(f"no JSON schema for {h!r}")


def _hint_generic(h: object, origin: object, args: tuple[object, ...]) -> dict[str, Json]:
    if origin is Union or origin is types.UnionType:
        return _nullable([_hint(a) for a in args if a is not type(None) and a is not Absent], type(None) in args)
    if origin is Literal:
        kinds = {type(a) for a in args}
        node: dict[str, Json] = {"enum": [a for a in args if a is None or isinstance(a, str | int | float | bool)]}
        if kinds == {str}:
            node = {"type": "string", **node}
        return node
    if origin in (list, set, frozenset):
        return {"type": "array", "items": _hint(args[0])}
    if origin is tuple:
        return {"type": "array", "items": _hint(args[0])} if len(args) == 2 and args[1] is Ellipsis else {"type": "array"}
    if origin is dict:
        return {"type": "object", "additionalProperties": _hint(args[1])}
    raise TypeError(f"no JSON schema for {h!r}")


def _nullable(members: list[dict[str, Json]], null: bool) -> dict[str, Json]:
    if len(members) != 1:
        return {"anyOf": [*members, *([{"type": "null"}] if null else [])]}
    node = dict(members[0])
    kind = node.get("type")
    if null and isinstance(kind, str):
        node["type"] = [kind, "null"]
        enum = node.get("enum")
        if isinstance(enum, list):
            node["enum"] = [*enum, None]
    return node


def strict(schema: dict[str, Json]) -> dict[str, Json]:
    """The contract as strict structured output takes it: every object requires all its properties, and a property the
    contract leaves optional may be null instead. Returns a copy."""
    sch = copy.deepcopy(schema)
    if sch.get("type") == "object":
        props = sch.get("properties", {})
        required = sch.get("required", [])
        if isinstance(props, dict):
            for k, v in list(props.items()):
                if not isinstance(v, dict):
                    continue
                node = props[k] = strict(v)
                if not isinstance(required, list) or k not in required:
                    kind = node.get("type")
                    if isinstance(kind, str):
                        node["type"] = [kind, "null"]
                    enum = node.get("enum")
                    if isinstance(enum, list):
                        node["enum"] = [*enum, None]
            sch["required"] = list(props)
    items = sch.get("items")
    if sch.get("type") == "array" and isinstance(items, dict):
        sch["items"] = strict(items)
    return sch
