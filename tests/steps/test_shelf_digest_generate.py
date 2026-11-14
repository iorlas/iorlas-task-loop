"""Whole-digest generation and byte-level canonical output from six pinned packages."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from shelf_digest_fixtures import COMMIT, SOURCE_COMMIT, complete_case, installed_case, objects

from taskloop.shelf_digest import generate
from taskloop.shelf_digest.documentation import DocumentationFailure
from taskloop.shelf_digest.generate import Digest, generate_digest, generate_installed_digest
from taskloop.shelf_digest.identities import PACKAGES, Identities, IdentityFailure
from taskloop.shelf_digest.models import Signature, SignatureFailure
from taskloop.shelf_digest.render import render_digest
from taskloop.shelf_digest.source import ReadFailure, SourceOpener


def test_six_packages_and_canonical_json_despite_input_order(tmp_path: Path) -> None:
    case = complete_case(tmp_path / "forward")
    result = generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    assert isinstance(result, Digest)
    assert tuple(item.name for item in result.identities.packages) == PACKAGES
    assert len(result.signatures) >= 6 and len(result.documentation) >= 12
    output = render_digest(result)
    reverse = complete_case(tmp_path / "reverse", reverse=True)
    repeated = generate_digest(reverse.root, SOURCE_COMMIT, reverse.shelf)
    assert isinstance(repeated, Digest) and render_digest(repeated) == output
    reordered = replace(result, identities=replace(result.identities, packages=tuple(reversed(result.identities.packages))),
                        signatures=tuple(reversed(result.signatures)), documentation=tuple(reversed(result.documentation)))
    assert render_digest(reordered) == output
    parsed = json.loads(output)
    assert parsed["source_commit"] == SOURCE_COMMIT
    assert [item[0] for item in parsed["packages"]] == list(PACKAGES)
    assert parsed["commits"] == [COMMIT]
    assert output == (json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    assert len(output) <= 2500
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


def test_installed_generation_matches_git_and_retains_stream_procs_version(tmp_path: Path) -> None:
    case = complete_case(tmp_path / "forward", stream_version="0.9")
    identities, distributions = installed_case(case)
    result = generate_installed_digest(case.root, SOURCE_COMMIT, distributions)
    assert isinstance(result, Digest) and result.identities == identities
    agent, stream = result.identities.packages[0], result.identities.packages[-1]
    assert (agent.version, stream.version) == ("1.0", "0.9")
    assert agent.commit == stream.commit == COMMIT and agent.requested_tag == stream.requested_tag
    assert result == generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    reverse = complete_case(tmp_path / "reverse", reverse=True, stream_version="0.9")
    _, reversed_distributions = installed_case(reverse)
    reordered = generate_installed_digest(reverse.root, SOURCE_COMMIT, reversed_distributions)
    assert isinstance(reordered, Digest) and render_digest(result) == render_digest(reordered)


def test_installed_generation_keeps_the_same_capture_for_both_extractors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = complete_case(tmp_path)
    _, distributions = installed_case(case)
    expected = generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    original = generate.extract_signatures

    def mutate_before_extraction(
        identities: Identities, opener: SourceOpener,
    ) -> tuple[Signature, ...] | SignatureFailure | ReadFailure:
        for record in distributions.records.values():
            record.contents.clear()
        return original(identities, opener)

    monkeypatch.setattr(generate, "extract_signatures", mutate_before_extraction)
    assert generate_installed_digest(case.root, SOURCE_COMMIT, distributions) == expected


@pytest.mark.parametrize(("path", "data", "expected"), [
    ("stream_proc/__init__.py", b'__all__ = ["missing"]', SignatureFailure),
    ("README.md", b"\xff", DocumentationFailure),
])
def test_installed_generation_returns_no_partial_digest_after_late_failure(
    tmp_path: Path, path: str, data: bytes, expected: type[SignatureFailure | DocumentationFailure],
) -> None:
    case = complete_case(tmp_path)
    _, distributions = installed_case(case)
    distributions.records["stream-proc"].contents[path] = data
    result = generate_installed_digest(case.root, SOURCE_COMMIT, distributions)
    assert isinstance(result, expected) and "stream-proc" in result.explanation


def test_installed_generation_does_not_fallback_on_identity_or_source_failure(tmp_path: Path) -> None:
    case = complete_case(tmp_path)
    _, distributions = installed_case(case)
    assert isinstance(generate_installed_digest(case.root, "missing", distributions), ReadFailure)
    del distributions.records["stream-proc"]
    result = generate_installed_digest(case.root, SOURCE_COMMIT, distributions)
    assert isinstance(result, IdentityFailure) and "stream-proc" in result.explanation
