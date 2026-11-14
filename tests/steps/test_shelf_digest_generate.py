"""Whole-digest generation and byte-level canonical output from six pinned packages."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from shelf_digest_fixtures import COMMIT, SOURCE_COMMIT, complete_case, objects

from taskloop.shelf_digest.documentation import DocumentationFailure
from taskloop.shelf_digest.generate import Digest, generate_digest
from taskloop.shelf_digest.identities import PACKAGES, IdentityFailure
from taskloop.shelf_digest.models import SignatureFailure
from taskloop.shelf_digest.render import render_digest
from taskloop.shelf_digest.source import ReadFailure


def test_six_packages_and_canonical_json_despite_input_order(tmp_path: Path) -> None:
    case = complete_case(tmp_path / "forward")
    result = generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    assert isinstance(result, Digest)
    assert tuple(item.name for item in result.identities.packages) == PACKAGES
    assert len(result.signatures) == 6 and len(result.documentation) == 12
    output = render_digest(result)
    reverse = complete_case(tmp_path / "reverse", reverse=True)
    repeated = generate_digest(reverse.root, SOURCE_COMMIT, reverse.shelf)
    assert isinstance(repeated, Digest) and render_digest(repeated) == output
    reordered = replace(result, identities=replace(result.identities, packages=tuple(reversed(result.identities.packages))),
                        signatures=tuple(reversed(result.signatures)), documentation=tuple(reversed(result.documentation)))
    assert render_digest(reordered) == output
    parsed = json.loads(output)
    assert parsed["source_commit"] == SOURCE_COMMIT
    assert [item["name"] for item in parsed["packages"]] == list(PACKAGES)
    assert all(item["commit"] == COMMIT for item in parsed["signatures"] + parsed["documentation"])
    assert output == (json.dumps(parsed, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    assert b"caf\xc3\xa9" in output and b"\\u00e9" not in output
    assert output.endswith(b"\n") and not output.endswith(b"\n\n") and b"\r" not in output
    assert str(tmp_path).encode() not in output


def test_changed_pin_and_documentation_are_reflected_only_at_selected_commit(tmp_path: Path) -> None:
    original = complete_case(tmp_path / "original")
    first = generate_digest(original.root, SOURCE_COMMIT, original.shelf)
    changed_commit = "d" * 40
    changed = complete_case(tmp_path / "changed", commit=changed_commit)
    path = "packages/stream-proc/README.md"
    changed.shelf_files[path] = b"Warning: new restriction.\nComplete example follows.\n"
    # Both commits are available; selection comes solely from the task-loop lock.
    changed.shelf.trees[COMMIT] = original.shelf.trees[COMMIT]
    second = generate_digest(changed.root, SOURCE_COMMIT, changed.shelf)
    assert isinstance(first, Digest) and isinstance(second, Digest)
    assert {item.commit for item in second.identities.packages} == {changed_commit}
    assert {item.commit for item in second.documentation} == {changed_commit}
    assert [item.declaration for item in first.signatures] == [item.declaration for item in second.signatures]
    assert next(item.text for item in second.documentation if item.path == path) == changed.shelf_files[path].decode()
    assert next(item.text for item in first.documentation if item.path == path) != changed.shelf_files[path].decode()
    assert render_digest(first) != render_digest(second)


def test_missing_revision_or_pinned_object_returns_only_failure(tmp_path: Path) -> None:
    case = complete_case(tmp_path)
    assert isinstance(generate_digest(case.root, "missing", case.shelf), ReadFailure)
    missing = objects(tmp_path / "missing", {})
    assert isinstance(generate_digest(case.root, SOURCE_COMMIT, missing), ReadFailure)


@pytest.mark.parametrize(("path", "data", "expected"), [
    ("pyproject.toml", b'[project]\nname = "wrong"\nversion = "1.0"', IdentityFailure),
    ("src/stream_proc/__init__.py", b'__all__ = ["missing"]', SignatureFailure),
    ("README.md", b"\xff", DocumentationFailure),
])
def test_late_package_failure_returns_no_partial_digest(
    tmp_path: Path, path: str, data: bytes, expected: type[IdentityFailure | SignatureFailure | DocumentationFailure],
) -> None:
    case = complete_case(tmp_path)
    case.shelf_files[f"packages/stream-proc/{path}"] = data
    result = generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    assert isinstance(result, expected) and "stream-proc" in result.explanation
