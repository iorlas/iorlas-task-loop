"""In-process results for static public signature extraction."""

from dataclasses import dataclass
from enum import StrEnum

from taskloop.shelf_digest.identities import PackageIdentity
from taskloop.shelf_digest.source import ReadFailure


class SignatureKind(StrEnum):
    FUNCTION = "function"
    CLASS = "class"
    CONSTANT = "constant"
    TYPE_ALIAS = "type_alias"
    MODULE = "module"


@dataclass(frozen=True)
class Signature:
    identity: PackageIdentity
    commit: str
    public_name: str
    defining_name: str
    path: str
    start_line: int
    end_line: int
    kind: SignatureKind
    declaration: str


class SignatureFailureReason(StrEnum):
    INVALID_SOURCE = "invalid_source"
    UNSUPPORTED_EXPORT = "unsupported_export"
    UNRESOLVED_EXPORT = "unresolved_export"
    NO_MODULE = "no_module"


@dataclass(frozen=True)
class SignatureFailure:
    reason: SignatureFailureReason
    explanation: str


class ExtractionError(Exception):
    """Carry an explained failure internally, without returning partial records."""

    def __init__(self, failure: SignatureFailure | ReadFailure) -> None:
        super().__init__(failure.explanation)
        self.failure = failure
