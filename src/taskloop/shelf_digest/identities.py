"""Reconcile shelf identities from one task-loop commit and the locked shelf manifests."""

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit, urlunsplit

from git_porcelain import Repo
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from taskloop.shelf_digest.source import CommittedSource, ReadFailure, open_source, relative_path

PACKAGES = ("any-agent", "beads-client", "git-porcelain", "process-lock", "sqlite-store", "stream-proc")


class IdentityFailureReason(StrEnum):
    INVALID_MANIFEST = "invalid_manifest"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class IdentityFailure:
    reason: IdentityFailureReason
    explanation: str


@dataclass(frozen=True)
class PackageIdentity:
    name: str
    version: str
    repository_url: str
    requested_tag: str
    subdirectory: str
    commit: str


@dataclass(frozen=True)
class Identities:
    source_commit: str
    packages: tuple[PackageIdentity, ...]


class _Edge(BaseModel):
    model_config = ConfigDict(strict=True)


class _Project(_Edge):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)


class _Source(_Edge):
    model_config = ConfigDict(strict=True, extra="forbid")
    git: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    subdirectory: str = Field(min_length=1)


class _Uv(_Edge):
    sources: dict[str, _Source]


class _Tool(_Edge):
    uv: _Uv


class _ProjectManifest(_Edge):
    project: _Project
    tool: _Tool


class _PackageManifest(_Edge):
    project: _Project


class _Dependency(_Edge):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str
    git: str | None = None
    specifier: str | None = None
    marker: str | None = None


class _Metadata(_Edge):
    requires_dist: list[_Dependency] = Field(alias="requires-dist")


class _LockedPackage(_Edge):
    name: str
    version: str
    source: dict[str, str]
    dependencies: list[_Dependency] = Field(default_factory=list)
    metadata: _Metadata | None = None


class _Lock(_Edge):
    package: list[_LockedPackage]


class _Invalid(ValueError):
    """An explained disagreement between committed inputs."""


def _manifest[M: BaseModel](source: CommittedSource, path: str, model: type[M]) -> M | ReadFailure | IdentityFailure:
    data = source.read(path)
    if isinstance(data, ReadFailure):
        return data
    try:
        return model.model_validate(tomllib.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValidationError) as error:
        return IdentityFailure(IdentityFailureReason.INVALID_MANIFEST, f"Invalid {path} at {source.commit}: {error}")


def _repository(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or not parsed.path or parsed.query or parsed.fragment:
        raise _Invalid(f"Unsupported repository URL {url!r}; expected an https or ssh repository without selectors")


def _selector(url: str, *, locked: bool) -> tuple[_Source, str]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, errors="strict")
    if set(query) != {"subdirectory", "tag"} or any(len(values) != 1 for values in query.values()):
        raise _Invalid(f"Unsupported source {url!r}; expected one subdirectory and one tag")
    commit = parsed.fragment
    if (locked and re.fullmatch(r"[0-9a-f]{40}", commit) is None) or (not locked and commit):
        raise _Invalid(f"Source {url!r}: expected {'a full immutable commit' if locked else 'no commit fragment'}")
    source = _Source(git=urlunsplit(parsed._replace(query="", fragment="")),
                     subdirectory=query["subdirectory"][0], tag=query["tag"][0])
    _repository(source.git)
    if not relative_path(source.subdirectory):
        raise _Invalid(f"Invalid package subdirectory {source.subdirectory!r} in {url!r}")
    return source, commit


def _one[T](items: list[T], context: str) -> T:
    if len(items) != 1:
        raise _Invalid(f"{context}: expected exactly one record, observed {len(items)}")
    return items[0]


def _equal(expected: object, observed: object, context: str) -> None:
    if expected != observed:
        raise _Invalid(f"{context}: expected {expected!r}, observed {observed!r}")


def _identity(name: str, project: _ProjectManifest, lock: _Lock, root: _LockedPackage) -> PackageIdentity:
    context = f"{name} in pyproject.toml / uv.lock"
    try:
        declaration = _one([item for item in project.project.dependencies
                            if re.split(r"[\s<>=!~\[;@]", item, maxsplit=1)[0] == name], context)
        matched = re.fullmatch(re.escape(name) + r"==([A-Za-z0-9][A-Za-z0-9.!+_-]*)", declaration)
        if matched is None:
            raise _Invalid(f"Expected an exact version for {name}, observed {declaration!r}")
        version = matched[1]
        declared = project.tool.uv.sources[name]
        _repository(declared.git)
        if not relative_path(declared.subdirectory):
            raise _Invalid(f"Invalid package subdirectory {declared.subdirectory!r}")
        package = _one([item for item in lock.package if item.name == name], context)
        _equal(version, package.version, f"{context} version")
        _equal({"git"}, set(package.source), f"{context} source fields")
        locked, commit = _selector(package.source["git"], locked=True)
        _equal(declared, locked, f"{context} source")
        dependency = _one([item for item in root.dependencies if item.name == name], f"{context} root dependency")
        _equal((None, None, None), (dependency.git, dependency.specifier, dependency.marker),
               f"{context} root dependency selectors")
        if root.metadata is None:
            raise _Invalid("Missing task-loop lock metadata")
        metadata = _one([item for item in root.metadata.requires_dist if item.name == name], f"{context} requires-dist")
        if metadata.git is None:
            raise _Invalid("Missing source in requires-dist")
        _equal(None, metadata.specifier, f"{context} requires-dist specifier")
        _equal(None, metadata.marker, f"{context} requires-dist marker")
        selected, _ = _selector(metadata.git, locked=False)
        _equal(declared, selected, f"{context} requires-dist source")
        return PackageIdentity(name, version, declared.git, declared.tag, declared.subdirectory, commit)
    except (ValueError, ValidationError) as error:
        raise _Invalid(f"{context}: {error}") from error


def _reconcile(project: _ProjectManifest, lock: _Lock) -> tuple[PackageIdentity, ...]:
    _equal(set(PACKAGES), set(project.tool.uv.sources), "pyproject.toml shelf source names")
    root = _one([item for item in lock.package if item.name == project.project.name], "uv.lock task-loop package")
    _equal(project.project.version, root.version, "uv.lock task-loop version")
    _equal({"editable": "."}, root.source, "uv.lock task-loop source")
    identities = tuple(_identity(name, project, lock, root) for name in PACKAGES)
    agent, stream = identities[0], identities[-1]
    _equal((agent.repository_url, agent.commit), (stream.repository_url, stream.commit),
           "any-agent / stream-proc uv.lock shared source commit")
    return identities


def _validate_package(identity: PackageIdentity, shelf: Repo) -> IdentityFailure | ReadFailure | None:
    path = f"{identity.subdirectory}/pyproject.toml"
    context = f"{identity.name}: {path} at {identity.commit}"
    package_source = open_source(shelf, identity.commit)
    if isinstance(package_source, ReadFailure):
        return ReadFailure(package_source.reason, f"{context}: {package_source.explanation}")
    manifest = _manifest(package_source, path, _PackageManifest)
    if isinstance(manifest, ReadFailure):
        return ReadFailure(manifest.reason, f"{identity.name}: {manifest.explanation}")
    if isinstance(manifest, IdentityFailure):
        return IdentityFailure(manifest.reason, f"{identity.name}: {manifest.explanation}")
    try:
        _equal((identity.name, identity.version), (manifest.project.name, manifest.project.version), context)
    except _Invalid as error:
        return IdentityFailure(IdentityFailureReason.MISMATCH, str(error))
    return None


def extract_identities(source: CommittedSource, shelf: Repo) -> Identities | IdentityFailure | ReadFailure:
    """Return all six identities, or one explained failure with no partial collection."""
    project = _manifest(source, "pyproject.toml", _ProjectManifest)
    if isinstance(project, (ReadFailure, IdentityFailure)):
        return project
    lock = _manifest(source, "uv.lock", _Lock)
    if isinstance(lock, (ReadFailure, IdentityFailure)):
        return lock
    try:
        identities = _reconcile(project, lock)
    except _Invalid as error:
        return IdentityFailure(IdentityFailureReason.MISMATCH, f"Task-loop source at {source.commit}: {error}")
    for identity in identities:
        failure = _validate_package(identity, shelf)
        if failure is not None:
            return failure
    return Identities(source.commit, identities)
