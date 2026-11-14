"""Verify attribution, cited bytes and the mandatory source contracts together."""

from hashlib import sha256

from taskloop.shelf_digest.facts import Evidence, Fact, FactFailure, FactFailureReason, collect_facts
from taskloop.shelf_digest.identities import Identities
from taskloop.shelf_digest.source import ReadFailure, SourceOpener, relative_path


def _verify(item: Evidence, identities: Identities, opener: SourceOpener) -> None:
    packages = {package.name: package for package in identities.packages}
    identity = packages.get(item.package)
    if identity is None or item.commit != identity.commit:
        raise ValueError("Evidence package or commit does not match its identity")
    if not relative_path(item.path) or not item.path.startswith(f"{identity.subdirectory}/src/"):
        raise ValueError("Evidence path is outside its package")
    source = opener(item.commit)
    if isinstance(source, ReadFailure) or source.commit != item.commit:
        raise ValueError("Evidence source commit does not match")
    data = source.read(item.path)
    if isinstance(data, ReadFailure):
        raise ValueError(data.explanation)
    lines = data.splitlines(keepends=True)
    if not 1 <= item.start_line <= item.end_line <= len(lines):
        raise ValueError("Evidence range is outside its source")
    if sha256(b"".join(lines[item.start_line - 1:item.end_line])).hexdigest() != item.sha256:
        raise ValueError("Evidence bytes have changed")


def validate_facts(identities: Identities, facts: tuple[Fact, ...], opener: SourceOpener) -> FactFailure | None:
    """A fresh hash alone never establishes a fact: repeat its AST predicates."""
    try:
        for fact in facts:
            for evidence in fact.evidence:
                _verify(evidence, identities, opener)
        expected = collect_facts(identities, opener)
        if isinstance(expected, FactFailure):
            return expected
        canonical = {fact.name: (fact.text, frozenset(fact.evidence)) for fact in facts}
        if len(canonical) != len(facts) or canonical != {fact.name: (fact.text, frozenset(fact.evidence)) for fact in expected}:
            raise ValueError("Mandatory facts or their evidence are missing, contradictory or misattributed")
    except ValueError as error:
        return FactFailure(FactFailureReason.EVIDENCE, f"Invalid shelf evidence: {error}")
    return None
