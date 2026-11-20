"""Observable committed-source outcomes through semantic Git objects."""

from pathlib import Path
from typing import override

import pytest
from git_porcelain import GitUnavailable, Sha, Tree
from git_porcelain.testing import FakeRemote, FakeRepo

from taskloop.shelf_digest.source import CommittedSource, ReadFailure, ReadFailureReason, SourceEntry, open_source

COMMIT = "a" * 40
BLOB = Sha("b" * 40)


@pytest.mark.parametrize("mode", ["100644", "100755", "120000", "160000", "040000", "100600"])
def test_only_regular_files_are_read(mode: str) -> None:
    reads: list[str] = []

    def read(path: str) -> bytes:
        reads.append(path)
        return b"committed bytes"

    source = CommittedSource(COMMIT, Tree(Sha(COMMIT), lambda: {"file": (mode, BLOB)}, read))
    assert source.entries() == (SourceEntry("file", mode, str(BLOB)),)
    result = source.read("file")
    if mode in {"100644", "100755"}:
        assert result == b"committed bytes" and reads == ["file"]
    else:
        assert isinstance(result, ReadFailure)
        assert result.reason == ReadFailureReason.NOT_A_FILE and not reads
        assert all(item in result.explanation for item in ("file", COMMIT, mode))


def test_absent_path_and_unreadable_listed_object_are_distinct() -> None:
    source = CommittedSource(COMMIT, Tree(Sha(COMMIT), lambda: {"lost": ("100644", BLOB)}, lambda _: None))
    for path, reason in [("absent", ReadFailureReason.NO_PATH), ("lost", ReadFailureReason.UNREADABLE)]:
        result = source.read(path)
        assert isinstance(result, ReadFailure)
        assert result.reason == reason
        assert path in result.explanation and COMMIT in result.explanation


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a//b", "a/./b", "a\\b", "a\x00b"])
def test_invalid_paths_are_refused_before_object_access(path: str) -> None:
    def uncalled() -> dict[str, tuple[str, Sha]]:
        pytest.fail("invalid path reached object listing")

    source = CommittedSource(COMMIT, Tree(Sha(COMMIT), uncalled, lambda _: None))
    result = source.read(path)
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.INVALID_PATH
    assert result.explanation


@pytest.mark.parametrize("listing", [True, False])
def test_infrastructure_failure_during_listing_or_read_is_explained(listing: bool) -> None:
    def files() -> dict[str, tuple[str, Sha]]:
        if listing:
            raise GitUnavailable("object storage unavailable")
        return {"file": ("100644", BLOB)}

    def read(_path: str) -> bytes:
        raise GitUnavailable("object storage unavailable")

    source = CommittedSource(COMMIT, Tree(Sha(COMMIT), files, read))
    result = source.read("file")
    assert isinstance(result, ReadFailure)
    assert result.reason == ReadFailureReason.UNAVAILABLE
    assert all(part in result.explanation for part in ("file", COMMIT, "object storage unavailable"))
    if listing:
        result = source.entries()
        assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.UNAVAILABLE
        assert COMMIT in result.explanation and "object storage unavailable" in result.explanation


class UnavailableRepo(FakeRepo):
    @override
    def tree(self, rev: str) -> Tree | None:
        raise GitUnavailable("repository offline")


def test_open_resolves_once_and_explains_missing_or_unavailable_commits(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    commit = remote.advance("main", {"file": "original"})
    repo = FakeRepo.clone(remote, tmp_path / "repo")
    source = open_source(repo, "HEAD")
    assert isinstance(source, CommittedSource) and source.commit == commit
    assert source.read("file") == b"original"
    for revision in ["missing", "-option"]:
        result = open_source(repo, revision)
        assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NO_COMMIT
        assert revision in result.explanation
    result = open_source(UnavailableRepo.init(tmp_path / "offline"), "HEAD")
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.UNAVAILABLE
    assert "repository offline" in result.explanation and "HEAD" in result.explanation
