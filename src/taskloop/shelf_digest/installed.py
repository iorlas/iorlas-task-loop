"""Validate installed identities and capture source without importing shelf packages."""

import csv
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from taskloop.shelf_digest.documentation import document_path
from taskloop.shelf_digest.identities import Identities, IdentityFailure, IdentityFailureReason, PackageIdentity
from taskloop.shelf_digest.source import ReadFailure, ReadFailureReason, SourceSnapshot, relative_path


class InstalledMetadata(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    direct_url: str = Field(min_length=1)


class Distribution(Protocol):
    def metadata(self) -> InstalledMetadata | IdentityFailure: ...

    def files(self) -> tuple[str, ...] | ReadFailure: ...

    def read(self, path: str) -> bytes | ReadFailure: ...


class Distributions(Protocol):
    def find(self, name: str) -> tuple[Distribution, ...]: ...


class _Vcs(StrEnum):
    GIT = "git"


class _VcsInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    vcs: _Vcs
    commit_id: str = Field(pattern=r"^[0-9a-f]{40}$")
    requested_revision: str = Field(min_length=1)


class _DirectUrl(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    url: str = Field(min_length=1)
    vcs_info: _VcsInfo
    subdirectory: str = Field(min_length=1)


@dataclass(frozen=True)
class _InstalledDistribution:
    distribution: metadata.Distribution

    def metadata(self) -> InstalledMetadata | IdentityFailure:
        try:
            fields = self.distribution.metadata
            for field in ("Name", "Version"):
                if len(fields.get_all(field) or ()) != 1:
                    return IdentityFailure(IdentityFailureReason.INVALID_METADATA, f"Expected one installed {field} field")
            return InstalledMetadata.model_validate({
                "name": fields["Name"], "version": fields["Version"],
                "direct_url": self.distribution.read_text("direct_url.json"),
            })
        except (OSError, UnicodeError, ValueError) as error:
            return IdentityFailure(IdentityFailureReason.INVALID_METADATA, f"Cannot read installed metadata: {error}")

    def files(self) -> tuple[str, ...] | ReadFailure:
        try:
            listing = self.distribution.read_text("RECORD")
            if listing is None:
                return ReadFailure(ReadFailureReason.UNREADABLE, "Installed file inventory is missing")
            # Distribution.files drops missing files and normalizes paths before callers can validate them.
            rows = tuple(csv.reader(StringIO(listing, newline=""), strict=True))
            if any(len(row) != 3 for row in rows):
                return ReadFailure(ReadFailureReason.UNREADABLE, "Invalid installed RECORD: expected three fields per file")
            return tuple(row[0] for row in rows)
        except (csv.Error, OSError, UnicodeError, ValueError) as error:
            return ReadFailure(ReadFailureReason.UNREADABLE, f"Cannot read installed file inventory: {error}")

    def read(self, path: str) -> bytes | ReadFailure:
        if not relative_path(path):
            return ReadFailure(ReadFailureReason.INVALID_PATH, f"Invalid installed path {path!r}")
        try:
            target = Path(str(self.distribution.locate_file("")))
            parts = PurePosixPath(path).parts
            for index, part in enumerate(parts):
                target /= part
                mode = target.lstat().st_mode
                regular = stat.S_ISREG(mode) if index == len(parts) - 1 else stat.S_ISDIR(mode)
                if not regular:
                    return ReadFailure(ReadFailureReason.NOT_A_FILE, f"Installed path {path!r} is not a regular source file")
            return target.read_bytes()
        except OSError as error:
            return ReadFailure(ReadFailureReason.UNREADABLE, f"Cannot read installed path {path!r}: {error}")


class InstalledDistributions:
    """The stdlib metadata adapter; package code is never imported or executed."""

    def find(self, name: str) -> tuple[Distribution, ...]:
        return tuple(_InstalledDistribution(item) for item in metadata.distributions(name=name))


def _validate(identity: PackageIdentity, distribution: Distribution) -> IdentityFailure | None:
    record = distribution.metadata()
    if isinstance(record, IdentityFailure):
        return IdentityFailure(record.reason, f"{identity.name}: {record.explanation}")
    try:
        direct = _DirectUrl.model_validate_json(record.direct_url)
    except ValidationError as error:
        return IdentityFailure(IdentityFailureReason.INVALID_METADATA, f"{identity.name}: invalid direct_url.json: {error}")
    observed = {
        "name": record.name, "version": record.version, "repository URL": direct.url,
        "commit": direct.vcs_info.commit_id, "requested tag": direct.vcs_info.requested_revision,
        "subdirectory": direct.subdirectory,
    }
    expected = {
        "name": identity.name, "version": identity.version, "repository URL": identity.repository_url,
        "commit": identity.commit, "requested tag": identity.requested_tag, "subdirectory": identity.subdirectory,
    }
    for field, value in expected.items():
        if observed[field] != value:
            return IdentityFailure(IdentityFailureReason.MISMATCH,
                                   f"{identity.name} installed {field}: expected {value!r}, observed {observed[field]!r}")
    return None


def _source_path(path: str, subdirectory: str) -> str | None:
    parts = PurePosixPath(path).parts
    if any(part.endswith((".dist-info", ".egg-info", ".data")) or part == "__pycache__" for part in parts):
        return None
    if path.endswith(".py"):
        return f"{subdirectory}/src/{path}"
    if document_path(path, ""):
        return f"{subdirectory}/{path}"
    return None


def _capture(identity: PackageIdentity, distribution: Distribution, captured: dict[str, bytes]) -> ReadFailure | None:
    paths = distribution.files()
    if isinstance(paths, ReadFailure):
        return ReadFailure(paths.reason, f"{identity.name}: {paths.explanation}")
    for path in paths:
        if not relative_path(path):
            return ReadFailure(ReadFailureReason.INVALID_PATH, f"{identity.name}: invalid installed path {path!r}")
    if len(paths) != len(set(paths)):
        return ReadFailure(ReadFailureReason.INVALID_PATH, f"{identity.name}: duplicate installed file paths")
    for path in sorted(paths):
        destination = _source_path(path, identity.subdirectory)
        if destination is None:
            continue
        data = distribution.read(path)
        if isinstance(data, ReadFailure):
            return ReadFailure(data.reason, f"{identity.name}: {path} at {identity.commit}: {data.explanation}")
        if destination in captured and captured[destination] != data:
            return ReadFailure(ReadFailureReason.INVALID_PATH, f"{identity.name}: conflicting source {destination} at {identity.commit}")
        captured[destination] = data
    return None


def capture_installed_sources(
    identities: Identities, distributions: Distributions,
) -> Mapping[str, SourceSnapshot] | IdentityFailure | ReadFailure:
    """Validate every identity before reading source; return only complete immutable captures."""
    selected: list[tuple[PackageIdentity, Distribution]] = []
    for identity in sorted(identities.packages, key=lambda item: item.name):
        try:
            candidates = distributions.find(identity.name)
        except (OSError, UnicodeError, ValueError) as error:
            return IdentityFailure(IdentityFailureReason.INVALID_METADATA, f"{identity.name}: cannot read installed metadata: {error}")
        if len(candidates) != 1:
            return IdentityFailure(IdentityFailureReason.INVALID_METADATA,
                                   f"{identity.name}: expected one installed distribution, observed {len(candidates)}")
        failure = _validate(identity, candidates[0])
        if failure is not None:
            return failure
        selected.append((identity, candidates[0]))
    captures: dict[str, dict[str, bytes]] = {}
    for identity, distribution in selected:
        failure = _capture(identity, distribution, captures.setdefault(identity.commit, {}))
        if failure is not None:
            return failure
    return {commit: SourceSnapshot(commit, files) for commit, files in sorted(captures.items())}
