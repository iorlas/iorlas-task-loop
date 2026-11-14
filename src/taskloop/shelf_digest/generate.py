"""Generate a complete digest from immutable task-loop and shelf sources."""

from dataclasses import dataclass

from git_porcelain import Repo

from taskloop.shelf_digest.documentation import Documentation, DocumentationFailure, extract_documentation
from taskloop.shelf_digest.facts import Fact, FactFailure, collect_facts
from taskloop.shelf_digest.identities import Identities, IdentityFailure, extract_identities, reconcile_manifests
from taskloop.shelf_digest.installed import Distributions, capture_installed_sources
from taskloop.shelf_digest.models import Signature, SignatureFailure
from taskloop.shelf_digest.signatures import extract_signatures
from taskloop.shelf_digest.source import ReadFailure, SourceOpener, open_source
from taskloop.shelf_digest.validation import validate_facts


@dataclass(frozen=True)
class Digest:
    identities: Identities
    signatures: tuple[Signature, ...]
    documentation: tuple[Documentation, ...]
    facts: tuple[Fact, ...]


def generate_digest(
    taskloop_repo: Repo, revision: str, shelf_repo: Repo,
) -> Digest | ReadFailure | IdentityFailure | SignatureFailure | DocumentationFailure | FactFailure:
    """Return all six packages, or an explained failure without a partial result."""
    source = open_source(taskloop_repo, revision)
    if isinstance(source, ReadFailure):
        return source
    identities = extract_identities(source, shelf_repo)
    if isinstance(identities, (ReadFailure, IdentityFailure)):
        return identities
    return _extract(identities, lambda commit: open_source(shelf_repo, commit))


def generate_installed_digest(
    taskloop_repo: Repo, revision: str, distributions: Distributions,
) -> Digest | ReadFailure | IdentityFailure | SignatureFailure | DocumentationFailure | FactFailure:
    """Generate from installed sources only, after reconciling the committed task-loop manifests."""
    source = open_source(taskloop_repo, revision)
    if isinstance(source, ReadFailure):
        return source
    identities = reconcile_manifests(source)
    if isinstance(identities, (ReadFailure, IdentityFailure)):
        return identities
    captures = capture_installed_sources(identities, distributions)
    if isinstance(captures, (ReadFailure, IdentityFailure)):
        return captures
    return _extract(identities, captures.__getitem__)


def _extract(
    identities: Identities, opener: SourceOpener,
) -> Digest | ReadFailure | SignatureFailure | DocumentationFailure | FactFailure:
    signatures = extract_signatures(identities, opener)
    if isinstance(signatures, (ReadFailure, SignatureFailure)):
        return signatures
    documentation = extract_documentation(identities, signatures, opener)
    if isinstance(documentation, (ReadFailure, DocumentationFailure)):
        return documentation
    facts = collect_facts(identities, opener)
    if isinstance(facts, FactFailure):
        return facts
    failure = validate_facts(identities, facts, opener)
    if failure is not None:
        return failure
    return Digest(identities, signatures, documentation, facts)
