"""schema.py: the six answer records generate the engine's own contracts, and their strict form is valid strict output."""
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import msgspec
import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import answers, schema, wire

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import contracts.test_response_format as strict_test  # noqa: E402
from contracts import samples  # noqa: E402
from taskloop.contracts import enums  # noqa: E402
from taskloop.contracts.wire import Rec  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "schemas"  # the hand-written schemas the engine sent before E6, frozen
VARIANTS = [(n, v) for n in answers.NODES for v in (False, True) if not v or n in answers.VISUAL]


def fixture(node: str, visual: bool, strict: bool = False) -> Any:
    name = node + ("-visual" if visual else "") + (".strict" if strict else "") + ".json"
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def canon(node: Any) -> Any:
    """The schema with `required` and `enum` order forgotten and an empty description dropped."""
    if isinstance(node, dict):
        out = {k: canon(v) for k, v in node.items() if k != "description"}
        for k in ("required", "enum"):
            if k in out:
                out[k] = sorted(out[k], key=repr)
        return out
    return [canon(x) for x in node] if isinstance(node, list) else node


class AnswerSchemas(Case):
    def test_each_answer_generates_the_contract_the_engine_sent_before(self):
        for node, visual in VARIANTS:
            with self.subTest(node, visual=visual):
                assert canon(answers.schema_for(node, visual)) == canon(fixture(node, visual))

    def test_each_strict_form_equals_the_one_sent_before_and_is_valid(self):
        for node, visual in VARIANTS:
            with self.subTest(node, visual=visual):
                sent = answers.sent_schema(node, visual)
                assert strict_test.strict_errors(sent) == []
                assert strict_test.nullable_errors(answers.schema_for(node, visual), sent) == []
                assert canon(sent) == canon(fixture(node, visual, True))

    def test_strict_returns_a_copy(self):
        contract = schema.of(answers.PlanAnswer)
        before = json.dumps(contract, sort_keys=True)
        schema.strict(contract)
        assert json.dumps(contract, sort_keys=True) == before

    def test_the_contract_form_fails_the_strict_check_where_a_field_is_optional(self):
        errs = strict_test.strict_errors(schema.of(answers.WriteAnswer))
        assert any("shots: a property not in required" in e for e in errs), errs

    def test_a_worker_answer_decodes_into_the_dataclass(self):
        data = {"items": [{"n": 1, "verdict": "settled", "evidence": "e", "why": "w", "kind": "checkable", "source": ""}]}
        got = wire.load(answers.VerifyAnswer, data)
        assert got.items[0].verdict == "settled"
        data["items"][0]["verdict"] = "maybe"
        with pytest.raises(ValueError):
            wire.load(answers.VerifyAnswer, data)

    def test_an_optional_field_may_be_left_out_of_an_answer(self):
        base = {"summary": "s", "checks_run": [], "question": "", "options": [], "decided": "", "bad_checks": [], "new_cases": [],
                "unchecked": []}
        got = wire.load(answers.WriteAnswer, base)
        assert (got.shots, got.flakes) == ([], [])
        assert wire.load(answers.Case, {"criterion": "c", "check": {"kind": "adhoc", "argv": ["k"], "reads": []},
                                                   "class": "taste"}).class_ == "taste"


class Generator(Case):
    def test_unset_is_omission_not_a_json_type(self):
        class Probe(Rec):
            detail: str | msgspec.UnsetType = msgspec.UNSET

        result = schema.of(Probe)
        assert result["properties"]["detail"] == {"type": "string"}
        assert result["required"] == []
        assert wire.dump(Probe()) == {}

    def test_scalars_enums_nullable_and_docs(self):

        class Probe(Rec):
            name: Annotated[str, msgspec.Meta(description="what it is called")]
            n: int
            ratio: float
            ok: bool
            kind: Literal["a", "b"]
            step: enums.Step
            maybe: str | None
            items: list[int] = msgspec.field(default_factory=list)
            table: dict[str, float] = msgspec.field(default_factory=dict)

        s = schema.of(Probe)
        assert s["required"] == ["name", "n", "ratio", "ok", "kind", "step", "maybe"]
        assert s["additionalProperties"] is False
        p = s["properties"]
        assert p["name"] == {"type": "string", "description": "what it is called"}
        assert (p["n"]["type"], p["ratio"]["type"], p["ok"]["type"]) == ("integer", "number", "boolean")
        assert p["kind"] == {"type": "string", "enum": ["a", "b"]}
        assert "plan" in p["step"]["enum"]
        assert p["maybe"]["type"] == ["string", "null"]
        assert p["items"] == {"type": "array", "items": {"type": "integer"}}
        assert p["table"] == {"type": "object", "additionalProperties": {"type": "number"}}
        strict = schema.strict(s)
        assert strict["required"] == list(p)
        assert strict["properties"]["items"]["type"] == ["array", "null"]

    def test_a_type_with_no_schema_is_an_error(self):
        class Bad(Rec):
            x: set[complex] = msgspec.field(default_factory=set)

        with pytest.raises(TypeError):
            schema.of(Bad)

    def test_every_top_level_record_has_a_schema_that_names_its_fields(self):
        for coll in (samples.LOG, samples.EVENTS, samples.LIVE, samples.OTHERS):
            for name, rec in coll.items():
                with self.subTest(name):
                    s = schema.of(type(rec))
                    assert list(s["properties"]) == list(wire.dump(rec))
