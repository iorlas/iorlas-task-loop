"""delegate-d6f: the schema subset checker follows JSON Schema on bool vs number, integral floats and unknown types."""

import hermetic  # noqa: F401  (a home of its own for every test)

from delegate.app.answer import schema_problem


class SchemaProblemTest:
    def test_true_is_not_the_enum_value_1(self):
        assert schema_problem(True, {"enum": [1]}) is not None
        assert schema_problem(0, {"enum": [False]}) is not None
        assert schema_problem([True], {"enum": [[1]]}) is not None
        assert schema_problem(True, {"enum": [True]}) is None
        assert schema_problem(1, {"enum": [1]}) is None

    def test_an_integral_float_is_an_integer(self):
        assert schema_problem(1.0, {"type": "integer"}) is None
        assert schema_problem(1.5, {"type": "integer"}) is not None
        assert schema_problem(True, {"type": "integer"}) is not None
        assert schema_problem(1.5, {"type": "number"}) is None

    def test_an_unknown_type_is_reported(self):
        assert "unsupported" in (schema_problem("x", {"type": "strng"}) or "")
        assert "unsupported" in (schema_problem("x", {"type": ["string", "date"]}) or "")
        assert schema_problem("x", {"type": ["string", "null"]}) is None
