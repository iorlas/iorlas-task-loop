"""Generate a complete digest from immutable task-loop and shelf sources."""

from dataclasses import dataclass

from git_porcelain import Repo

from taskloop.shelf_digest.documentation import Documentation, DocumentationFailure, extract_documentation
from taskloop.shelf_digest.identities import Identities, IdentityFailure, extract_identities
from taskloop.shelf_digest.models import Signature, SignatureFailure
from taskloop.shelf_digest.signatures import extract_signatures
from taskloop.shelf_digest.source import ReadFailure, open_source


@dataclass(frozen=True)
class Digest:
    identities: Identities
    signatures: tuple[Signature, ...]
    documentation: tuple[Documentation, ...]


def generate_digest(
    taskloop_repo: Repo, revision: str, shelf_repo: Repo,
) -> Digest | ReadFailure | IdentityFailure | SignatureFailure | DocumentationFailure:
    """Return all six packages, or an explained failure without a partial result."""
    source = open_source(taskloop_repo, revision)
    if isinstance(source, ReadFailure):
        return source
    identities = extract_identities(source, shelf_repo)
    if isinstance(identities, (ReadFailure, IdentityFailure)):
        return identities
    signatures = extract_signatures(identities, shelf_repo)
    if isinstance(signatures, (ReadFailure, SignatureFailure)):
        return signatures
    documentation = extract_documentation(identities, signatures, shelf_repo)
    if isinstance(documentation, (ReadFailure, DocumentationFailure)):
        return documentation
    return Digest(identities, signatures, documentation)
