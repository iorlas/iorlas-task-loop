"""Check the ontology YAMLs against a2kay's own META_SCHEMA and field type grammar (run with a2kay's venv python)."""

import sys
from pathlib import Path

import yaml
from a2kay.core.field_types import parse
from a2kay.core.meta_schema import META_SCHEMA
from jsonschema import Draft202012Validator

validator = Draft202012Validator(META_SCHEMA)
bad = 0
for path in sorted(Path(sys.argv[1]).glob("*.yml")):
    doc = yaml.safe_load(path.read_text())
    problems = [e.message[:100] for e in validator.iter_errors(doc)]
    problems += [f"field {f['name']}: type {f.get('type')!r} not in a2kay grammar" for f in doc.get("fields", []) if f.get("type") and parse(f["type"]) is None]
    print(path.name, "OK" if not problems else problems)
    bad += bool(problems)
sys.exit(1 if bad else 0)
