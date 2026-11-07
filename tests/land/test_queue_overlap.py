"""Pure code overlap cases from merge-queue design section 11."""
import pytest

from taskloop.domain.land.queue_overlap import claims, overlaps, waits_for


@pytest.mark.parametrize(("a", "b", "expected"), [
    (["src/a"], ["src/a"], True),
    (["src/a"], ["src/a/b.py"], True),
    (["src/a/b.py"], ["src/a"], True),
    (["src/a"], ["src/ab"], False),
    ([], ["src/a"], False),
])
def test_overlaps(a: list[str], b: list[str], expected: bool) -> None:
    assert overlaps(a, b) is expected


@pytest.mark.parametrize(("touched", "conflicts", "expected"), [
    ({"a": ["src"], "b": ["src/a"], "c": ["src/a/b"]},
     frozenset(), {"b": "a", "c": "b"}),
    ({"a": ["a"], "b": ["b"], "c": ["c"]},
     frozenset({frozenset({"a", "c"})}), {"c": "a"}),
    ({"a": ["a"], "b": ["b"]}, frozenset(), {}),
    ({}, frozenset(), {}),
])
def test_waits_for(
    touched: dict[str, list[str]], conflicts: frozenset[frozenset[str]],
    expected: dict[str, str],
) -> None:
    assert waits_for(["a", "b", "c"], touched, conflicts) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("## Touches\n- `src/a`\n• `src/b`\n- src/c\n## Other\n- ignored",
     ["src/a", "src/b", "src/c"]),
    ("## Other\n- src/a", []),
    ("", []),
    ("## Touches\n\n- src/a\n# End\n- ignored", ["src/a"]),
])
def test_claims(text: str, expected: list[str]) -> None:
    assert claims(text) == expected
