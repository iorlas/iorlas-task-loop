"""Validate the bounded interchange artifact without reopening shelf sources."""

import json
import re

from pydantic import BaseModel, ConfigDict

from taskloop.shelf_digest.facts import CONTRACTS, FactName
from taskloop.shelf_digest.identities import Identities, PackageIdentity
from taskloop.shelf_digest.source import relative_path

PATH = "docs/shelf-digest.json"
TOKEN_LIMIT = 2500


class DigestArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_commit: str
    repositories: tuple[str, ...]
    commits: tuple[str, ...]
    # package: name, version, repository index, requested tag, subdirectory, commit index.
    packages: tuple[tuple[str, str, int, str, str, int], ...]
    # source: package index, package-relative path, first line, last line, SHA-256.
    sources: tuple[tuple[int, str, int, int, str], ...]
    facts: dict[FactName, tuple[str, tuple[int, ...]]]

    def encode(self, limit: int = TOKEN_LIMIT) -> bytes:
        output = (json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(output) > limit:
            raise ValueError(f"Shelf digest exceeds conservative {limit}-token bound ({len(output)} UTF-8 bytes)")
        return output


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate shelf digest field: {key}")
        result[key] = value
    return result


def _hash(value: str, size: int) -> bool:
    return re.fullmatch(f"[0-9a-f]{{{size}}}", value) is not None


def _identities(artifact: DigestArtifact, identities: Identities) -> None:
    if not _hash(artifact.source_commit, 40):
        raise ValueError("Invalid shelf digest source_commit")
    expected = identities.packages
    if (artifact.repositories != tuple(sorted({p.repository_url for p in expected}))
            or artifact.commits != tuple(sorted({p.commit for p in expected}))):
        raise ValueError("Shelf digest repository/commit identities do not match pyproject.toml / uv.lock")
    expanded = []
    for name, version, repository, tag, directory, commit in artifact.packages:
        if not 0 <= repository < len(artifact.repositories) or not 0 <= commit < len(artifact.commits):
            raise ValueError(f"Invalid shelf digest identity index for {name}")
        expanded.append(PackageIdentity(name, version, artifact.repositories[repository], tag, directory, artifact.commits[commit]))
    if tuple(expanded) != expected:
        raise ValueError("Shelf digest package identities do not match pyproject.toml / uv.lock")


def _facts(artifact: DigestArtifact) -> None:
    if set(artifact.facts) != set(FactName) or len(set(artifact.sources)) != len(artifact.sources):
        raise ValueError("Shelf digest has missing facts or duplicate sources")
    for package, path, start, end, checksum in artifact.sources:
        if (not 0 <= package < len(artifact.packages) or not relative_path(path)
                or start != 1 or end < start or not _hash(checksum, 64)):
            raise ValueError("Invalid shelf digest source path, range, hash or package index")
    used: set[int] = set()
    for contract in CONTRACTS:
        text, references = artifact.facts[contract.name]
        expected = {(rule.package, f"src/{rule.package.replace('-', '_')}/{rule.module}.py") for rule in contract.rules}
        if (text != contract.text or not references or tuple(sorted(set(references))) != references
                or any(index < 0 or index >= len(artifact.sources) for index in references)):
            raise ValueError(f"Invalid shelf digest fact or references: {contract.name}")
        observed = {(artifact.packages[artifact.sources[index][0]][0], artifact.sources[index][1]) for index in references}
        if observed != expected or len(references) != len(expected):
            raise ValueError(f"Invalid shelf digest fact attribution: {contract.name}")
        used.update(references)
    if used != set(range(len(artifact.sources))):
        raise ValueError("Shelf digest contains unreferenced sources")


def read_artifact(data: bytes, identities: Identities) -> DigestArtifact:
    """Validate selected manifest identities and retained facts; provenance need not equal HEAD."""
    if len(data) > TOKEN_LIMIT:
        raise ValueError(f"Shelf digest exceeds conservative {TOKEN_LIMIT}-token bound ({len(data)} UTF-8 bytes)")
    artifact = DigestArtifact.model_validate_json(data, strict=True)
    json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    _identities(artifact, identities)
    _facts(artifact)
    artifact.encode()
    return artifact
