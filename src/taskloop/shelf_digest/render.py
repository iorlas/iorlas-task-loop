"""One validated JSON boundary and canonical UTF-8 serializer."""

import json

from pydantic import BaseModel, ConfigDict

from taskloop.shelf_digest.documentation import DocumentationKind, documentation_order
from taskloop.shelf_digest.generate import Digest
from taskloop.shelf_digest.models import SignatureKind


class _Record(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class _Identity(_Record):
    name: str
    version: str
    repository_url: str
    requested_tag: str
    subdirectory: str
    commit: str


class _Signature(_Record):
    identity: _Identity
    commit: str
    public_name: str
    defining_name: str
    path: str
    start_line: int
    end_line: int
    kind: SignatureKind
    declaration: str


class _Documentation(_Record):
    identity: _Identity
    commit: str
    path: str
    start_line: int
    end_line: int
    kind: DocumentationKind
    text: str
    public_name: str | None
    defining_name: str | None


class _Digest(_Record):
    source_commit: str
    packages: tuple[_Identity, ...]
    signatures: tuple[_Signature, ...]
    documentation: tuple[_Documentation, ...]


def render_digest(digest: Digest) -> bytes:
    """Sort records and keys, preserve text values, and emit exactly one final LF."""
    result = _Digest(
        source_commit=digest.identities.source_commit,
        packages=tuple(_Identity.model_validate(item) for item in sorted(digest.identities.packages, key=lambda item: item.name)),
        signatures=tuple(_Signature.model_validate(item) for item in sorted(
            digest.signatures, key=lambda item: (item.identity.name, item.path, item.start_line, item.end_line, item.public_name))),
        documentation=tuple(_Documentation.model_validate(item) for item in sorted(digest.documentation, key=documentation_order)),
    )
    text = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")
