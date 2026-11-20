"""Required contracts, stale evidence and the complete conservative output bound."""

import json
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from shelf_digest_fixtures import COMMIT, SOURCE_COMMIT, Case, complete_case, installed_case

from taskloop.shelf_digest.facts import Evidence, FactFailure, FactName
from taskloop.shelf_digest.generate import Digest, generate_digest, generate_installed_digest
from taskloop.shelf_digest.render import TOKEN_LIMIT, render_digest
from taskloop.shelf_digest.source import SourceSnapshot
from taskloop.shelf_digest.validation import validate_facts


@pytest.fixture
def generated(tmp_path: Path) -> tuple[Case, Digest, SourceSnapshot]:
    case = complete_case(tmp_path)
    digest = generate_digest(case.root, SOURCE_COMMIT, case.shelf)
    assert isinstance(digest, Digest)
    return case, digest, SourceSnapshot(COMMIT, case.shelf_files)


def test_required_facts_and_source_references_survive(generated: tuple[Case, Digest, SourceSnapshot]) -> None:
    _, digest, source = generated
    assert validate_facts(digest.identities, digest.facts, lambda _: source) is None
    parsed = json.loads(render_digest(digest))
    assert set(parsed["facts"]) == set(FactName)
    for fact in digest.facts:
        text, references = parsed["facts"][fact.name]
        assert text == fact.text and references
        for index in references:
            package, path, start, end, checksum = parsed["sources"][index]
            identity = parsed["packages"][package]
            data = source.read(f"{identity[4]}/{path}")
            assert isinstance(data, bytes)
            assert checksum == sha256(b"".join(data.splitlines(keepends=True)[start - 1:end])).hexdigest()
    assert all(name in parsed["facts"]["summary"][0] for name in ("text", "res", "facts", "cost", "live.end", "SIGKILL"))


@pytest.mark.parametrize("change", [
    lambda e: replace(e, package="beads-client"), lambda e: replace(e, package="missing"),
    lambda e: replace(e, commit="f" * 40), lambda e: replace(e, path="../escape.py"),
    lambda e: replace(e, path="packages/any-agent/src/any_agent/missing.py"),
    lambda e: replace(e, start_line=0), lambda e: replace(e, end_line=999999), lambda e: replace(e, sha256="0" * 64),
])
def test_stale_or_misattributed_evidence_fails(
    generated: tuple[Case, Digest, SourceSnapshot], change: Callable[[Evidence], Evidence],
) -> None:
    _, digest, source = generated
    fact = digest.facts[0]
    altered = change(fact.evidence[0])
    facts = (replace(fact, evidence=(altered, *fact.evidence[1:])), *digest.facts[1:])
    failure = validate_facts(digest.identities, facts, lambda _: source)
    assert isinstance(failure, FactFailure) and failure.explanation


@pytest.mark.parametrize("kind", ["missing", "duplicate", "assertion", "bytes", "commit"])
def test_incomplete_or_changed_evidence_fails(generated: tuple[Case, Digest, SourceSnapshot], kind: str) -> None:
    case, digest, source = generated
    facts = digest.facts
    if kind == "missing":
        facts = facts[1:]
    elif kind == "duplicate":
        facts = (*facts, facts[0])
    elif kind == "assertion":
        facts = (replace(facts[0], text="Timeout is monotonic"), *facts[1:])
    elif kind == "bytes":
        files = dict(case.shelf_files)
        files[facts[0].evidence[0].path] += b"\n# changed\n"
        source = SourceSnapshot(COMMIT, files)
    else:
        source = SourceSnapshot("f" * 40, case.shelf_files)
    assert isinstance(validate_facts(digest.identities, facts, lambda _: source), FactFailure)


@pytest.mark.parametrize("module,old,new", [
    ("any-agent/src/any_agent/supervisor.py", b"self.clock() + timeout", b"self.clock() - timeout"),
    ("any-agent/src/any_agent/watch.py", b"self.start += gap", b"self.start -= gap"),
    ("any-agent/src/any_agent/supervisor.py", b"self.hooks.started(worker)", b"self.hooks.started(None)"),
    ("stream-proc/src/stream_proc/registered.py", b"_cleanup(child)", b"pass"),
    ("any-agent/src/any_agent/protocol.py", b"cost: float = 0.0", b"cost: str = ''"),
    ("any-agent/src/any_agent/supervisor.py", b"rc = -signal.SIGKILL", b"rc = 0"),
    ("any-agent/src/any_agent/events.py", b"usage: Tokens | None", b"usage: Tokens"),
    ("git-porcelain/src/git_porcelain/real_write.py", b'"--detach"', b'"--force"'),
])
def test_new_hash_cannot_validate_a_contradictory_contract(
    generated: tuple[Case, Digest, SourceSnapshot], module: str, old: bytes, new: bytes,
) -> None:
    case, digest, _ = generated
    path = "packages/" + module
    assert old in case.shelf_files[path]
    case.shelf_files[path] = case.shelf_files[path].replace(old, new)
    source = SourceSnapshot(COMMIT, case.shelf_files)
    facts = tuple(replace(fact, evidence=tuple(
        replace(e, sha256=sha256(case.shelf_files[path]).hexdigest()) if e.path == path else e for e in fact.evidence
    )) for fact in digest.facts)
    assert isinstance(validate_facts(digest.identities, facts, lambda _: source), FactFailure)
    _, distributions = installed_case(case)
    failure = generate_installed_digest(case.root, SOURCE_COMMIT, distributions)
    assert isinstance(failure, FactFailure) and failure.explanation


def test_order_and_huge_optional_material_do_not_change_output(generated: tuple[Case, Digest, SourceSnapshot]) -> None:
    _, digest, _ = generated
    expected = render_digest(digest)
    changed = replace(digest,
                      identities=replace(digest.identities, packages=tuple(reversed(digest.identities.packages))),
                      facts=tuple(replace(fact, evidence=tuple(reversed(fact.evidence))) for fact in reversed(digest.facts)),
                      signatures=tuple(replace(s, declaration="a" * 100000) for s in digest.signatures),
                      documentation=tuple(replace(d, text="é" * 100000 + "\ud800") for d in digest.documentation))
    assert render_digest(changed) == expected


def test_complete_utf8_json_exact_ceiling_and_overflow(generated: tuple[Case, Digest, SourceSnapshot]) -> None:
    _, digest, _ = generated
    fact = digest.facts[0]
    escaped = replace(digest, facts=(replace(fact, text=fact.text + 'é\\"\n'), *digest.facts[1:]))
    output = render_digest(escaped)
    assert b'\xc3\xa9' in output and b'\\n' in output and output.endswith(b"\n")
    padding = "a" * (TOKEN_LIMIT - len(output))
    exact = replace(escaped, facts=(replace(escaped.facts[0], text=escaped.facts[0].text + padding), *escaped.facts[1:]))
    assert len(render_digest(exact)) == TOKEN_LIMIT
    over = replace(exact, facts=(replace(exact.facts[0], text=exact.facts[0].text + "a"), *exact.facts[1:]))
    with pytest.raises(ValueError, match="2500-token bound"):
        render_digest(over)
    huge = replace(digest, identities=replace(digest.identities, source_commit="a" * 2500))
    with pytest.raises(ValueError, match="2500-token bound"):
        render_digest(huge)
