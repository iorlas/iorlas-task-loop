"""The check owner's vocabulary."""
from enum import StrEnum


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    CACHED = "cached"
    UNVERIFIED = "unverified"
