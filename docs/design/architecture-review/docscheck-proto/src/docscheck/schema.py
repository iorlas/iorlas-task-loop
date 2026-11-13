"""Kinds to JSON Schema (draft 2020-12) and frontmatter validation."""

from jsonschema import Draft202012Validator

from docscheck.ontology import Field, Kind, TypeSpec
from docscheck.values import Finding, Json

_SCALAR: dict[str, dict[str, Json]] = {
    "string": {"type": "string", "minLength": 1}, "int": {"type": "integer"}, "float": {"type": "number"},
    "bool": {"type": "boolean"}, "datetime": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}"}, "object": {"type": "object"},
}


def _one(spec: TypeSpec, kinds: dict[str, Kind], field: Field) -> dict[str, Json]:
    if spec.base in _SCALAR:
        schema = dict(_SCALAR[spec.base])
        if field.max_len is not None:
            schema["maxLength"] = field.max_len
        return schema
    if spec.base == "enum":
        return {"enum": list(spec.values)}
    if spec.base == "link":
        names = "|".join(spec.targets) if "any" not in spec.targets else "[a-z_]+"
        pattern = rf"^({names})/[A-Za-z0-9][A-Za-z0-9._-]*$"
        return {"oneOf": [{"type": "string", "pattern": pattern}, {"const": field.default}]} if field.default else {"type": "string", "pattern": pattern}
    return row_schema(kinds[spec.targets[0]], kinds)


def field_schema(field: Field, kinds: dict[str, Kind]) -> dict[str, Json]:
    item = _one(field.type, kinds, field)
    if field.type.shape == "one":
        return item
    array: dict[str, Json] = {"type": "array", "items": item}
    if field.type.shape == "set":
        array["uniqueItems"] = True
    return array


def row_schema(kind: Kind, kinds: dict[str, Kind]) -> dict[str, Json]:
    props: dict[str, Json] = {field.name: field_schema(field, kinds) for field in kind.fields}
    required: list[Json] = [field.name for field in kind.fields if field.required]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def validate_frontmatter(doc_id: str, kind: Kind, kinds: dict[str, Kind], data: dict[str, Json]) -> list[Finding]:
    validator = Draft202012Validator(row_schema(kind, kinds))
    found: list[Finding] = []
    for error in sorted(validator.iter_errors(data), key=lambda item: item.json_path):
        message = error.message if len(error.message) < 140 else error.message[:137] + "..."
        found.append(Finding(doc_id, error.json_path.removeprefix("$.") or "frontmatter", "schema", message))
    return found
