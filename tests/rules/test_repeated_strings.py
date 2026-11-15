"""Repeated executable strings require constants; existing exceptions may only shrink."""

import ast
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS = Path(__file__).with_name("repeated_string_exceptions.json")
CENSUS = TypeAdapter(dict[str, dict[str, Annotated[int, Field(strict=True, gt=0)]]])


def repeated_string_sites(sources: Mapping[str, str]) -> dict[str, dict[str, list[int]]]:
    sites: dict[str, dict[str, list[int]]] = {}
    for path, source in sorted(sources.items()):
        tree = ast.parse(source, filename=path)
        excluded: set[ast.Constant] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    excluded.add(first.value)
            if isinstance(node, ast.JoinedStr):
                excluded.update(value for value in node.values if isinstance(value, ast.Constant))
        literals: dict[str, list[int]] = defaultdict(list)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in excluded:
                literals[node.value].append(node.lineno)
        repeated = {value: sorted(lines) for value, lines in sorted(literals.items()) if len(lines) >= 3}
        if repeated:
            sites[path] = repeated
    return sites


def assert_string_census(sites: dict[str, dict[str, list[int]]], exceptions: dict[str, dict[str, int]]) -> None:
    actual = {(path, value): lines for path, values in sites.items() for value, lines in values.items()}
    expected = {(path, value): count for path, values in exceptions.items() for value, count in values.items()}
    added = {key: actual[key] for key in actual.keys() - expected.keys()}
    changed = {key: (expected[key], actual[key]) for key in actual.keys() & expected.keys() if len(actual[key]) != expected[key]}
    stale = expected.keys() - actual.keys()
    assert not added, "New repeated strings (path, value): lines: " + str(added)
    assert not changed, "Update repeated string counts (path, value): (expected count, actual lines): " + str(changed)
    assert not stale, "Remove resolved repeated string exceptions: " + str(sorted(stale))
    assert all(exceptions.values()), "Remove empty module entries from repeated string exceptions"


def test_repository_repeated_strings_require_constants() -> None:
    sources = {path.relative_to(ROOT).as_posix(): path.read_text() for path in (ROOT / "src/taskloop").rglob("*.py")}
    # Initial census at ce583887. Remove or reduce resolved entries; never add entries to pass.
    exceptions = CENSUS.validate_json(EXCEPTIONS.read_text())
    assert_string_census(repeated_string_sites(sources), exceptions)


@pytest.mark.parametrize("value", ["repeated", "", "x"])
def test_three_literals_fail_but_a_shared_constant_passes(value: str) -> None:
    repeated = f"a = {value!r}\nb = {value!r}\ndef read():\n    return {value!r}"
    with pytest.raises(AssertionError, match="New repeated strings"):
        assert_string_census(repeated_string_sites({"module.py": repeated}), {})
    shared = f"TEXT = {value!r}\na = TEXT\nb = TEXT\ndef read():\n    return TEXT"
    assert_string_census(repeated_string_sites({"module.py": shared}), {})


def test_two_occurrences_per_module_pass() -> None:
    source = "first = 'same'\nsecond = 'same'"
    assert_string_census(repeated_string_sites({"first.py": source, "second.py": source}), {})


def test_docstrings_comments_bytes_and_fstring_text_are_excluded() -> None:
    source = '''
"same"
class Reader:
    "same"
    def read(self):
        "same"
async def read():
    "same"
# 'same' 'same' 'same'
raw = [b'same', b'same', b'same']
text = [f'same{1}', f'same{2}', f'same{3}']
formatted = [f'{1:same}', f'{2:same}', f'{3:same}']
'''
    assert_string_census(repeated_string_sites({"module.py": source}), {})


@pytest.mark.parametrize("source", [
    "items = [f\"{'same'}\", f\"{'same'}\", f\"{'same'}\"]",
    "items = [f\"{1:{'same'}}\", f\"{2:{'same'}}\", f\"{3:{'same'}}\"]",
    "items = ['sa' 'me', 's\\x61me', \"same\"]",
    "def first():\n    return 'same'\ndef second():\n    return 'same'\nclass Reader:\n    text = 'same'",
    "value = 1\n'same'\n'same'\n'same'",
])
def test_executable_literals_are_counted_by_decoded_value_across_the_module(source: str) -> None:
    sites = repeated_string_sites({"module.py": source})
    assert len(sites["module.py"]["same"]) == 3
    with pytest.raises(AssertionError, match="New repeated strings"):
        assert_string_census(sites, {})


@pytest.mark.parametrize("sources", [
    {"module.py": "items = ['same', 'same', 'same', 'same']"},
    {"module.py": "items = ['other', 'other', 'other']"},
    {"moved.py": "items = ['same', 'same', 'same']"},
    {"module.py": "items = ['same', 'same']"},
    {},
])
def test_increased_changed_moved_or_stale_exceptions_fail(sources: dict[str, str]) -> None:
    with pytest.raises(AssertionError):
        assert_string_census(repeated_string_sites(sources), {"module.py": {"same": 3}})


def test_formatting_preserves_identity_and_resolved_counts_require_baseline_shrinkage() -> None:
    sites = repeated_string_sites({"module.py": '\n# comment\nitems = [\n    "same", "same", "same",\n]'})
    assert_string_census(sites, {"module.py": {"same": 3}})
    with pytest.raises(AssertionError, match="Update repeated string counts"):
        assert_string_census(sites, {"module.py": {"same": 4}})
    assert_string_census({}, {})
    with pytest.raises(AssertionError, match="Remove empty module entries"):
        assert_string_census({}, {"module.py": {}})


@pytest.mark.parametrize("document", [
    '{"module.py": {"same": 0}}',
    '{"module.py": {"same": -1}}',
    '{"module.py": {"same": true}}',
    '{"module.py": {"same": "3"}}',
    '{"module.py": {"same": 3.5}}',
    '{"module.py": ["same"]}',
])
def test_exception_data_requires_nested_positive_integer_counts(document: str) -> None:
    with pytest.raises(ValidationError):
        CENSUS.validate_json(document)
