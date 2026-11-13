"""Kind definitions in a2kay's YAML shape: kinds, fields and the field type grammar."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ruamel.yaml import YAML

from docscheck.values import Finding, Json, as_list, as_map, as_str, plain

type Base = Literal["string", "int", "float", "bool", "datetime", "object", "link", "enum", "inline"]
SCALAR_BASE: dict[str, Base] = {
    "string": "string", "int": "int", "float": "float", "bool": "bool", "datetime": "datetime", "object": "object",
}
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_LINK = re.compile(rf"^link\[(?P<t>{_NAME}(?:\|{_NAME})*)\]$")
_LIST = re.compile(r"^(?P<shape>list|set)\[(?P<item>.*)\]$")
_ENUM = re.compile(r"^enum\[(?P<v>.*)\]$")
_INLINE = re.compile(rf"^{_NAME}$")


@dataclass(frozen=True)
class TypeSpec:
    """What a type token means: how many (`one`, `list`, `set`) of what (`base`)."""

    shape: Literal["one", "list", "set"]
    base: Base
    targets: tuple[str, ...] = ()
    values: tuple[str, ...] = ()


def _base(token: str, shape: Literal["one", "list", "set"]) -> TypeSpec | None:
    if token in SCALAR_BASE:
        return TypeSpec(shape, SCALAR_BASE[token])
    link = _LINK.match(token)
    if link:
        targets = tuple(link.group("t").split("|"))
        return None if "any" in targets and len(targets) > 1 else TypeSpec(shape, "link", targets=targets)
    enum = _ENUM.match(token)
    if enum and shape == "one":
        values = tuple(part.strip() for part in enum.group("v").split("<"))
        return TypeSpec(shape, "enum", values=values) if all(values) else None
    if _INLINE.match(token) and shape != "one":
        return TypeSpec(shape, "inline", targets=(token,))
    return None


def parse_type(token: str) -> TypeSpec | None:
    wrapped = _LIST.match(token)
    if wrapped:
        shape: Literal["list", "set"] = "list" if wrapped.group("shape") == "list" else "set"
        return _base(wrapped.group("item"), shape)
    return _base(token, "one")


@dataclass(frozen=True)
class Field:
    name: str
    type: TypeSpec
    required: bool = False
    default: str | None = None
    rigid: bool = False
    path: bool = False
    glob: bool = False
    symbol: bool = False
    max_len: int | None = None


@dataclass(frozen=True)
class Kind:
    name: str
    inline: bool
    key: str
    keys: tuple[str, ...]
    scope: Literal["global", "owner", "doc"]
    derived: str
    file_pattern: str
    fields: tuple[Field, ...]
    when_to_use: str
    body: str

    def field(self, name: str) -> Field | None:
        return next((item for item in self.fields if item.name == name), None)


def _field(raw: dict[str, Json], kind: str, found: list[Finding]) -> Field | None:
    name = as_str(raw.get("name"))
    spec = parse_type(as_str(raw.get("type")) or "string")
    if spec is None:
        found.append(Finding(f"ontology/{kind}", name, "bad-type", f"type token {raw.get('type')!r} is not in the grammar"))
        return None
    default = raw.get("default")
    limit = raw.get("max")
    return Field(
        name, spec, raw.get("required") is True, None if default is None else str(default), raw.get("rigid") is True,
        raw.get("path") is True, raw.get("glob") is True, raw.get("symbol") is True, limit if isinstance(limit, int) else None,
    )


def _kind(raw: dict[str, Json], found: list[Finding]) -> Kind:
    name = as_str(raw.get("name"))
    fields = tuple(item for item in (_field(as_map(entry), name, found) for entry in as_list(raw.get("fields"))) if item)
    scope = as_str(raw.get("scope")) or "doc"
    key = as_str(raw.get("key"))
    keys = tuple(as_str(item) for item in as_list(raw.get("keys"))) or ((key,) if key else ())
    return Kind(
        name, raw.get("storage") == "inline", key, keys, "global" if scope == "global" else "owner" if scope == "owner" else "doc",
        as_str(raw.get("derived")), as_str(raw.get("file_pattern")), fields, as_str(raw.get("when_to_use")), as_str(raw.get("body")) or "optional",
    )


def _consistent(kinds: dict[str, Kind], found: list[Finding]) -> None:
    for kind in kinds.values():
        if not kind.when_to_use:
            found.append(Finding(f"ontology/{kind.name}", "when_to_use", "missing", "every kind says when to use it"))
        for field in kind.fields:
            for target in field.type.targets:
                known = field.type.base == "link" and (target in kinds or target in {"any", "task"})
                known = known or field.type.base == "inline" and target in kinds and kinds[target].inline
                if field.type.base in {"link", "inline"} and not known:
                    found.append(Finding(f"ontology/{kind.name}", field.name, "unknown-kind", f"{target!r} is not a declared kind"))


def load_kinds(directory: Path) -> tuple[dict[str, Kind], list[Finding]]:
    yaml = YAML(typ="safe")
    found: list[Finding] = []
    kinds: dict[str, Kind] = {}
    for path in sorted(directory.glob("*.yml")):
        raw = as_map(plain(yaml.load(path.read_text())))
        kind = _kind(raw, found)
        kinds[kind.name] = kind
    _consistent(kinds, found)
    return kinds, found
