"""The stored reason of an attempt that repeats an earlier one after a failed required check (the vocabulary only)."""

from enum import StrEnum


class CheckRepeatReason(StrEnum):
    FAILED_CHECK = "failed_check"
