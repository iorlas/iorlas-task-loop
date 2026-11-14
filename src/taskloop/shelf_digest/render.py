"""Canonical JSON with a conservative one-token-per-UTF-8-byte upper bound."""

import json

from pydantic import BaseModel, ConfigDict

from taskloop.shelf_digest.facts import FactName
from taskloop.shelf_digest.generate import Digest

TOKEN_LIMIT = 2500


class _Digest(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_commit: str
    repositories: tuple[str, ...]
    commits: tuple[str, ...]
    # package: name, version, repository index, requested tag, subdirectory, commit index.
    packages: tuple[tuple[str, str, int, str, str, int], ...]
    # source: package index, package-relative path, first line, last line, SHA-256.
    sources: tuple[tuple[int, str, int, int, str], ...]
    facts: dict[FactName, tuple[str, tuple[int, ...]]]


def render_digest(digest: Digest) -> bytes:
    """Remove optional extraction material, retaining every identity and mandatory fact."""
    if len(digest.facts) != len(FactName) or {fact.name for fact in digest.facts} != set(FactName):
        raise ValueError("Cannot render digest: mandatory facts are missing or duplicated")
    packages = sorted(digest.identities.packages, key=lambda item: item.name)
    package_indices = {item.name: index for index, item in enumerate(packages)}
    repositories = tuple(sorted({item.repository_url for item in packages}))
    commits = tuple(sorted({item.commit for item in packages}))
    evidence = sorted({item for fact in digest.facts for item in fact.evidence}, key=lambda item: (
        item.package, item.path, item.start_line, item.end_line, item.sha256))
    evidence_indices = {item: index for index, item in enumerate(evidence)}
    directories = {item.name: item.subdirectory for item in packages}
    result = _Digest(
        source_commit=digest.identities.source_commit, repositories=repositories, commits=commits,
        packages=tuple((p.name, p.version, repositories.index(p.repository_url), p.requested_tag, p.subdirectory,
                        commits.index(p.commit)) for p in packages),
        sources=tuple((package_indices[e.package], e.path.removeprefix(directories[e.package] + "/"),
                       e.start_line, e.end_line, e.sha256) for e in evidence),
        facts={fact.name: (fact.text, tuple(sorted(evidence_indices[e] for e in fact.evidence))) for fact in digest.facts},
    )
    output = (json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(output) > TOKEN_LIMIT:
        raise ValueError(f"Shelf digest exceeds conservative {TOKEN_LIMIT}-token bound ({len(output)} UTF-8 bytes)")
    return output
