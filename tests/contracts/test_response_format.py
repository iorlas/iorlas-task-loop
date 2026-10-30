"""The response_format contract: every schema the engine sends a worker is one OpenAI strict structured output accepts
(tl-7y6.4.2). The trust-night storm of 22 Oct 20:42 (53 bad_request rows, 53 beads blocked, 26 asks, 254 min / 1.5M
tokens) was exactly this unsaid: the contract went out raw, its optional fields not nullable, `source` missing from
`required`. engine.strict makes the wire form; these tests hold that promise for every schema, both shapes walked."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

from taskloop.contracts import answers, schema  # noqa: E402

PRE_FIX_UNCHECKED = ROOT / "tests" / "fixtures" / "schemas" / "pre_fix_unchecked.json"


def types_of(schema):
    """The schema's type(s): strict output sends a nullable one as a list (["object", "null"]), a plain one as a string."""
    t = schema.get("type")
    return set(t) if isinstance(t, list) else ({t} if t else set())


def strict_errors(schema, path="$"):
    """[why `schema` is not valid for OpenAI strict structured output]: an object without additionalProperties:false, a
    property missing from required, a name required that is no property. Reads a nullable type as the object or array it
    still is: a walk that matches only a string type sees nothing nested under an optional object or array."""
    errs = []
    if "object" in types_of(schema):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            errs.append(f"{path}: additionalProperties is not false")
        for k in sorted(props):
            if k not in schema.get("required", []):
                errs.append(f"{path}.{k}: a property not in required")
        for k in schema.get("required", []):
            if k not in props:
                errs.append(f"{path}.{k}: required but not a property")
        for k in sorted(props):
            errs += strict_errors(props[k], f"{path}.{k}")
    if "array" in types_of(schema) and isinstance(schema.get("items"), dict):
        errs += strict_errors(schema["items"], path + "[]")
    return errs


def nullable_errors(contract, sent, path="$"):
    """[why a property the contract leaves optional cannot be null in `sent`, its strict form]: strict output requires
    every field, so the worker answers null for an optional one and the wire schema has to allow it — the type a union
    with null, the enum with None ('Missing source', 2026-10-22)."""
    errs = []
    if "object" in types_of(contract):
        props, sprops = contract.get("properties", {}), sent.get("properties", {})
        for k in sorted(props):
            if k not in contract.get("required", []):
                sp = sprops.get(k, {})
                if "type" in props[k] and "null" not in types_of(sp):
                    errs.append(f"{path}.{k}: optional but not nullable")
                if "enum" in props[k] and None not in sp.get("enum", []):
                    errs.append(f"{path}.{k}: an optional enum that does not take null")
            errs += nullable_errors(props[k], sprops.get(k, {}), f"{path}.{k}")
    if "array" in types_of(contract) and isinstance(contract.get("items"), dict):
        errs += nullable_errors(contract["items"], sent.get("items") or {}, path + "[]")
    return errs


def variants():
    """[(label, contract)]: every response_format the engine can send — each node's contract, and a visual stage's
    write/review with its look field added."""
    for node in sorted(answers.NODES):
        for visual in (False, True):
            if not visual or node in answers.VISUAL:
                yield "{}{}".format(node, " (visual)" if visual else ""), answers.schema_for(node, visual)


class ResponseFormatContracts(unittest.TestCase):
    def test_all_response_formats_are_strict(self):
        """Every schema the engine sends (planner, writer, reviewer, verifier, look, reflect; a visual stage's variants
        too) is valid strict output: every properties key in required, additionalProperties:false, at any depth."""
        for label, contract in variants():
            self.assertEqual(strict_errors(schema.strict(contract)), [], label)

    def test_optional_properties_are_nullable(self):
        """What the contract leaves optional, the strict form sent accepts as null — enum values included, so a worker
        that answers null for a field it must always send validates against the contract once mapped back."""
        for label, contract in variants():
            self.assertEqual(nullable_errors(contract, schema.strict(contract)), [], label)

    def test_pre_fix_unchecked_fixture_is_rejected(self):
        """The write step's unchecked.items exactly as it went out before the 2026-10-23 fix (ebee8e5): `source` in
        properties, absent from required, and every Codex write step rejected it (invalid_json_schema, 53 runs). The
        same checker that passes HEAD fails on this fixture, names where, and passes its strict conversion."""
        broken = json.loads(PRE_FIX_UNCHECKED.read_text(encoding="utf-8"))
        errs = strict_errors(broken)
        self.assertTrue(errs)
        self.assertTrue(all("source" in e for e in errs), errs)  # the diagnostic is a path to the offending property
        self.assertEqual(schema.strict(broken)["properties"]["source"]["type"], ["string", "null"])
        self.assertEqual(strict_errors(schema.strict(broken)), [])

    def test_walker_rejects_nested_nullable_violations(self):
        """A violation under an optional array of optional objects cannot pass: the walk reads a nullable type (a list)
        as the object or array it still is, so nesting hides nothing."""
        def sent():
            return {"type": "object", "additionalProperties": False, "required": ["rows"],
                    "properties": {"rows": {"type": ["array", "null"], "items": {
                        "type": ["object", "null"], "additionalProperties": False, "required": ["inner", "note"],
                        "properties": {"inner": {"type": "object", "additionalProperties": False,
                                                 "required": ["who"], "properties": {"who": {"type": "string"}}},
                                       "note": {"type": ["string", "null"]}}}}}}
        self.assertEqual(strict_errors(sent()), [])
        missing = sent()
        missing["properties"]["rows"]["items"]["properties"]["inner"]["required"] = []
        self.assertEqual(strict_errors(missing), ["$.rows[].inner.who: a property not in required"])
        loose = sent()
        del loose["properties"]["rows"]["items"]["additionalProperties"]
        self.assertEqual(strict_errors(loose), ["$.rows[]: additionalProperties is not false"])


if __name__ == "__main__":
    unittest.main()
