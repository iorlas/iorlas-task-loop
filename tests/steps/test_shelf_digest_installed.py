"""Installed metadata is checked before source capture, with immutable extraction inputs."""

from dataclasses import replace
from importlib import metadata
from pathlib import Path

import pytest
from shelf_digest_fixtures import COMMIT, complete_case, installed_case

from taskloop.shelf_digest.documentation import extract_documentation
from taskloop.shelf_digest.identities import IdentityFailure, IdentityFailureReason
from taskloop.shelf_digest.installed import InstalledDistributions, capture_installed_sources
from taskloop.shelf_digest.signatures import extract_signatures
from taskloop.shelf_digest.source import ReadFailure, ReadFailureReason, SourceSnapshot


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_installed_distribution_fails_before_capture(tmp_path: Path, duplicate: bool) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    if duplicate:
        distributions.duplicates = ("stream-proc",)
    else:
        del distributions.records["stream-proc"]
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, IdentityFailure)
    assert "stream-proc" in result.explanation and f"observed {2 if duplicate else 0}" in result.explanation
    assert not any(record.reads for record in distributions.records.values())


@pytest.mark.parametrize(("field", "value"), [("name", "other"), ("version", "0.9.0")])
def test_installed_name_and_version_must_match(tmp_path: Path, field: str, value: str) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    record = distributions.records["stream-proc"]
    record.record = record.record.model_copy(update={field: value})
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, IdentityFailure) and result.reason == IdentityFailureReason.MISMATCH
    assert all(word in result.explanation for word in ("stream-proc", field, "expected", "observed", value))
    assert not any(record.reads for record in distributions.records.values())


@pytest.mark.parametrize(("old", "new", "field"), [
    ('"url": "https://example.invalid/shelf.git"', '"url": "https://other.invalid/repo"', "repository URL"),
    ('"url": "https://example.invalid/shelf.git"', '"url": "https://example.invalid/shelf.git?tag=main"', "repository URL"),
    (COMMIT, "e" * 40, "commit"), (COMMIT, "abc", "commit_id"),
    ('"requested_revision": "any-agent-v1.0"', '"requested_revision": "main"', "requested tag"),
    ('"subdirectory": "packages/stream-proc"', '"subdirectory": "../outside"', "subdirectory"),
    ('"vcs": "git"', '"vcs": "hg"', "vcs"),
    ('"vcs": "git"', '"vcs": "git", "branch": "main"', "branch"),
    ('"commit_id":', '"missing_commit":', "commit_id"),
    ('"requested_revision": "any-agent-v1.0"', '"requested_revision": 4', "requested_revision"),
])
def test_invalid_or_disagreeing_direct_url_fails_with_context(
    tmp_path: Path, old: str, new: str, field: str,
) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    record = distributions.records["stream-proc"]
    assert old in record.record.direct_url
    record.record = record.record.model_copy(update={"direct_url": record.record.direct_url.replace(old, new)})
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, IdentityFailure)
    assert "stream-proc" in result.explanation and field in result.explanation
    assert not any(record.reads for record in distributions.records.values())


@pytest.mark.parametrize("direct_url", ["{", "null", "[]", '{"url": "local", "dir_info": {"editable": true}}'])
def test_malformed_metadata_is_an_explained_failure(tmp_path: Path, direct_url: str) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    record = distributions.records["any-agent"]
    record.record = record.record.model_copy(update={"direct_url": direct_url})
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, IdentityFailure) and result.reason == IdentityFailureReason.INVALID_METADATA
    assert "any-agent" in result.explanation and "direct_url.json" in result.explanation


@pytest.mark.parametrize("path", ["../outside.py", "/absolute.py", "demo/../bad.py", "demo\\bad.py", "demo//bad.py", "bad\n.py"])
def test_unsafe_inventory_paths_are_rejected_before_reads(tmp_path: Path, path: str) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    record = distributions.records["any-agent"]
    record.contents[path] = b"not read"
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.INVALID_PATH
    assert "any-agent" in result.explanation and repr(path) in result.explanation
    assert not record.reads


def test_capture_is_shared_by_extractors_and_isolated_from_later_mutation(tmp_path: Path) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    record = distributions.records["any-agent"]
    record.contents["any_agent-1.0.dist-info/README.md"] = ReadFailure(ReadFailureReason.UNREADABLE, "bookkeeping")
    captures = capture_installed_sources(identities, distributions)
    assert not isinstance(captures, (ReadFailure, IdentityFailure))
    snapshot = captures[COMMIT]
    paths = [entry.path for entry in snapshot.entries()]
    assert paths == sorted(paths)
    assert "packages/any-agent/src/any_agent/__init__.py" in paths
    assert "packages/stream-proc/src/stream_proc/__init__.py" in paths
    assert not any("dist-info" in path or "pyproject.toml" in path for path in paths)
    signatures = extract_signatures(identities, captures.__getitem__)
    assert isinstance(signatures, tuple) and len(signatures) == 6
    for distribution in distributions.records.values():
        assert len(distribution.reads) == len(distribution.contents) - sum("dist-info" in p for p in distribution.contents)
        assert len(set(distribution.reads)) == len(distribution.reads)
        distribution.contents.clear()
    docs = extract_documentation(identities, signatures, captures.__getitem__)
    assert isinstance(docs, tuple) and len(docs) == 19
    assert sum("Module warning." in item.text or "Only valid when idle." in item.text for item in docs) == 12
    files = {"module.py": b"VALUE = 1"}
    independent = SourceSnapshot(COMMIT, files)
    files["module.py"] = b"changed"
    assert independent.read("module.py") == b"VALUE = 1"


def test_selected_unreadable_source_returns_no_capture(tmp_path: Path) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    path = "stream_proc/__init__.py"
    distributions.records["stream-proc"].contents[path] = ReadFailure(ReadFailureReason.UNREADABLE, "cannot read bytes")
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.UNREADABLE
    assert all(part in result.explanation for part in ("stream-proc", path, COMMIT, "cannot read bytes"))


def test_shared_commit_conflicting_source_is_rejected(tmp_path: Path) -> None:
    identities, distributions = installed_case(complete_case(tmp_path))
    first = identities.packages[0]
    shared = replace(identities.packages[-1], subdirectory=first.subdirectory)
    identities = replace(identities, packages=(first, shared))
    record = distributions.records["stream-proc"]
    record.record = record.record.model_copy(update={
        "direct_url": record.record.direct_url.replace("packages/stream-proc", first.subdirectory),
    })
    result = capture_installed_sources(identities, distributions)
    assert isinstance(result, ReadFailure) and "conflicting source" in result.explanation


@pytest.mark.parametrize(("change", "reason"), [
    ("directory", ReadFailureReason.NOT_A_FILE), ("symlink", ReadFailureReason.NOT_A_FILE),
    ("missing", ReadFailureReason.UNREADABLE), ("parent_symlink", ReadFailureReason.NOT_A_FILE),
    ("missing_inventory", ReadFailureReason.UNREADABLE), ("duplicate_inventory", ReadFailureReason.INVALID_PATH),
    ("invalid_inventory", ReadFailureReason.UNREADABLE), ("unsafe_inventory", ReadFailureReason.INVALID_PATH),
])
def test_stdlib_adapter_captures_files_and_rejects_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, reason: ReadFailureReason,
) -> None:
    identities, distributions = installed_case(complete_case(tmp_path / "case"))
    identity = identities.packages[0]
    identities = replace(identities, packages=(identity,))
    info = tmp_path / "any_agent-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: any-agent\nVersion: 1.0\n")
    (info / "direct_url.json").write_text(distributions.records["any-agent"].record.direct_url)
    (info / "RECORD").write_text("any_agent.py,,\n")
    module = tmp_path / "any_agent.py"
    module.write_bytes(b'"""Installed module."""\nVALUE = 1\n')
    distribution = metadata.Distribution.at(info)
    monkeypatch.setattr(metadata, "distributions", lambda **_kwargs: (distribution,))
    adapter = InstalledDistributions()
    result = capture_installed_sources(identities, adapter)
    assert not isinstance(result, (ReadFailure, IdentityFailure))
    assert result[COMMIT].read("packages/any-agent/src/any_agent.py") == module.read_bytes()
    module.unlink()
    if change == "directory":
        module.mkdir()
    elif change == "symlink":
        module.symlink_to(info / "METADATA")
    elif change == "parent_symlink":
        (tmp_path / "any_agent").symlink_to(info, target_is_directory=True)
        (info / "RECORD").write_text("any_agent/METADATA,,\nany_agent/source.py,,\n")
        (info / "source.py").write_bytes(b"VALUE = 1")
    elif change == "missing_inventory":
        (info / "RECORD").unlink()
    elif change == "duplicate_inventory":
        (info / "RECORD").write_text("any_agent.py,,\nany_agent.py,,\n")
    elif change == "invalid_inventory":
        (info / "RECORD").write_text("any_agent.py,\n")
    elif change == "unsafe_inventory":
        (info / "RECORD").write_text("any_agent//source.py,,\n")
    failed = capture_installed_sources(identities, adapter)
    assert isinstance(failed, ReadFailure) and failed.reason == reason
    assert "any-agent" in failed.explanation


@pytest.mark.parametrize(("metadata_text", "direct_url"), [
    ("Name: any-agent\n", "{}"), ("Name: any-agent\nVersion: 1.0\nVersion: 2.0\n", "{}"),
    ("Name: any-agent\nVersion: 1.0\n", None),
])
def test_stdlib_adapter_rejects_missing_or_ambiguous_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata_text: str, direct_url: str | None,
) -> None:
    identities, _ = installed_case(complete_case(tmp_path / "case"))
    info = tmp_path / "any_agent-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(metadata_text)
    if direct_url is not None:
        (info / "direct_url.json").write_text(direct_url)
    monkeypatch.setattr(metadata, "distributions", lambda **_kwargs: (metadata.Distribution.at(info),))
    result = capture_installed_sources(replace(identities, packages=identities.packages[:1]), InstalledDistributions())
    assert isinstance(result, IdentityFailure) and result.reason == IdentityFailureReason.INVALID_METADATA
    assert "any-agent" in result.explanation
