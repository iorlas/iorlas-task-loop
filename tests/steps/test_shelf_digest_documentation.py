"""Documentation retains qualifications and alias provenance without executing source."""

from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from git_porcelain import Sha, Tree
from shelf_digest_fixtures import COMMIT, SOURCE_COMMIT, objects

from taskloop.shelf_digest.documentation import DocumentationFailure, DocumentationKind, extract_documentation
from taskloop.shelf_digest.identities import Identities, PackageIdentity
from taskloop.shelf_digest.signatures import extract_signatures
from taskloop.shelf_digest.source import ReadFailure, ReadFailureReason, open_source

IDENTITY = PackageIdentity("example", "1.0", "https://example.invalid/shelf", "example-v1.0", "packages/example", COMMIT)
PREFIX = "packages/example/"


def test_complete_text_and_alias_member_overload_provenance(tmp_path: Path) -> None:
    implementation = (
        '"""Implementation: only safe while idle."""\n'
        'from typing import overload\n'
        'class Example:\n'
        '    """Warning: acquire first.\n\n    Example:\n        with lock: ...\n    """\n'
        '    def __init__(self):\n        """Does not acquire."""\n'
        '    async def read(self):\n        """May fail. Retry only after release."""\n'
        '    @property\n    def ready(self):\n        """True only at observation time."""\n'
        '    class Nested:\n        """Nested qualification."""\n'
        '        def run(self):\n            """Nested example."""\n'
        '    def _hidden(self):\n        """Private text."""\n'
        '@overload\ndef call(value: int) -> int:\n    """Integer overload restriction."""\n'
        '@overload\ndef call(value: str) -> str:\n    """String overload restriction."""\n'
        'def call(value):\n    """Implementation warning."""\n'
        '__all__ = ["Example", "call"]\n'
        'raise RuntimeError("must never execute")\n'
    )
    readme = "# API\r\n\r\nOnly while idle.\r\n\r\nExample: café\r\nWarning:\u2028retry later.\r\n"
    files = {
        PREFIX + "src/demo/__init__.py": b'"""Public module."""\nfrom ._impl import Example as API, call\nfrom . import _impl as tools\n',
        PREFIX + "src/demo/_impl.py": implementation.encode(),
        PREFIX + "README": readme.encode(), PREFIX + "guide.rst": b"Qualifications\n=============\nAll conditions apply.\n",
        PREFIX + "docs/warning.txt": b"Warning without a final newline", PREFIX + "docs/example": b"Complete example\n",
        PREFIX + "docs/picture.png": b"\xff", "packages/elsewhere/README.md": b"irrelevant",
    }
    repo = objects(tmp_path, {COMMIT: files})
    identities = Identities(SOURCE_COMMIT, (IDENTITY,))
    signatures = extract_signatures(identities, partial(open_source, repo))
    assert isinstance(signatures, tuple)
    docs = extract_documentation(identities, signatures, partial(open_source, repo))
    assert isinstance(docs, tuple)
    document = next(item for item in docs if item.path == PREFIX + "README")
    assert document.text == readme and (document.start_line, document.end_line) == (1, 6)
    assert document.identity == IDENTITY and document.commit == COMMIT
    assert len([item for item in docs if item.kind == DocumentationKind.DOCUMENT]) == 4
    api = next(item for item in docs if item.public_name == "demo.API")
    assert api.defining_name == "demo._impl.Example" and api.path == PREFIX + "src/demo/_impl.py"
    assert (api.start_line, api.end_line) == (4, 8)
    assert api.text == "Warning: acquire first.\n\n    Example:\n        with lock: ...\n    "
    names = {item.public_name for item in docs}
    assert {"demo.API.__init__", "demo.API.read", "demo.API.ready", "demo.API.Nested.run", "demo.tools.Example"} <= names
    assert not any("Private text" in item.text for item in docs)
    calls = [item for item in docs if item.public_name == "demo.call"]
    assert [item.text for item in calls] == [
        "Integer overload restriction.", "String overload restriction.", "Implementation warning.",
    ]
    assert all(item.defining_name == "demo._impl.call" for item in calls)
    assert len([item for item in docs if item.public_name == "demo.tools" and item.kind == DocumentationKind.MODULE]) == 1


def test_absent_docs_and_python_encoding_are_supported(tmp_path: Path) -> None:
    files = {PREFIX + "src/demo.py": '# coding: latin-1\n"""café; only after release."""\ndef call():\n    pass\n'.encode("latin-1")}
    repo = objects(tmp_path, {COMMIT: files})
    identities = Identities(SOURCE_COMMIT, (IDENTITY,))
    signatures = extract_signatures(identities, partial(open_source, repo))
    assert isinstance(signatures, tuple)
    docs = extract_documentation(identities, signatures, partial(open_source, repo))
    assert isinstance(docs, tuple) and len(docs) == 1 and docs[0].text == "café; only after release."
    empty = objects(tmp_path / "empty", {COMMIT: {PREFIX + "src/demo.py": b"VALUE = 1\n"}})
    assert extract_documentation(identities, (), partial(open_source, empty)) == ()


@pytest.mark.parametrize("data", [b"\xff", b"broken\x80text"])
def test_invalid_late_document_returns_only_explained_failure(tmp_path: Path, data: bytes) -> None:
    later = replace(IDENTITY, name="later", subdirectory="packages/later")
    repo = objects(tmp_path, {COMMIT: {PREFIX + "README.md": b"valid", "packages/later/docs/end.txt": data}})
    result = extract_documentation(Identities(SOURCE_COMMIT, (later, IDENTITY)), (), partial(open_source, repo))
    assert isinstance(result, DocumentationFailure)
    assert "later" in result.explanation and "docs/end.txt" in result.explanation and COMMIT in result.explanation


@pytest.mark.parametrize(("mode", "data", "reason"), [
    ("120000", b"target", ReadFailureReason.NOT_A_FILE), ("100644", None, ReadFailureReason.UNREADABLE),
])
def test_listed_docs_must_be_readable_regular_files(
    tmp_path: Path, mode: str, data: bytes | None, reason: ReadFailureReason,
) -> None:
    path = PREFIX + "README.md"
    repo = objects(tmp_path, {})
    repo.trees = {COMMIT: Tree(Sha(COMMIT), lambda: {path: (mode, Sha("c" * 40))}, lambda _: data)}
    result = extract_documentation(Identities(SOURCE_COMMIT, (IDENTITY,)), (), partial(open_source, repo))
    assert isinstance(result, ReadFailure) and result.reason == reason
    assert path in result.explanation and COMMIT in result.explanation
