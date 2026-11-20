"""The claim codec preserves exact spellings and member identity."""

import pytest

from taskloop.claim import ClaimWord, decode_claim, encode_claim


@pytest.mark.parametrize(
    ("word", "text"),
    [(ClaimWord.HELD, "held"), (ClaimWord.LOST, "lost"), (ClaimWord.UNRENEWED, "unrenewed"), (ClaimWord.FAULT, "fault")],
)
def test_exact_claim_spellings_round_trip(word: ClaimWord, text: str) -> None:
    assert encode_claim(word) == text
    assert decode_claim(text) is word
    assert decode_claim(encode_claim(word)) is word


@pytest.mark.parametrize(
    "text",
    ["", "unknown", "Held", "LOST", "Unrenewed", "FAULT", " held", "held ", "lost\n", "\tfault"],
)
def test_invalid_claim_spellings_fail(text: str) -> None:
    with pytest.raises(ValueError):
        decode_claim(text)
