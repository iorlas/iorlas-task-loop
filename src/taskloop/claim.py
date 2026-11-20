"""The claim outcomes and their exact external spellings."""

from enum import StrEnum


class ClaimWord(StrEnum):
    HELD = "held"
    LOST = "lost"
    UNRENEWED = "unrenewed"
    FAULT = "fault"


def decode_claim(text: str) -> ClaimWord:
    """Decode an exact claim spelling, rejecting unknown spellings."""
    return ClaimWord(text)


def encode_claim(word: ClaimWord) -> str:
    """Encode a claim outcome with its exact external spelling."""
    return word.value
