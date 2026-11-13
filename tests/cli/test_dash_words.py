"""The page's one table of words for typed codes (`words.js`): the codes the data shapes carry are all in it, so none shows raw."""

import re
from pathlib import Path

import pytest

from taskloop.dash_verify import CHECKS

PAGE = Path(__file__).resolve().parents[2] / "src/taskloop/dash/static"
REQUIRED = (
    "needs_owner", "failed:needs_owner", "answer:schema_invalid", "failed:answer:schema_invalid", "failed:test:failed", "held:slot_dirty",
    "verified", "reused", "unsettled:branch", "unsettled:unsafe", "unsettled:ignored", "unsettled:uncommitted", "unsettled:rejected",
    "pending", "registered", "passed",
)


def table() -> dict[str, str]:
    block = re.search(r"export const WORDS = \{(.*?)\n\};", (PAGE / "words.js").read_text(), re.S)
    assert block is not None
    return dict(re.findall(r'^\s*"?([\w:]+)"?:\s*"(.*)",$', block.group(1), re.M))


@pytest.mark.parametrize("code", REQUIRED)
def test_a_typed_code_of_the_data_shapes_has_words(code: str) -> None:
    assert table().get(code), code


def test_the_verification_reasons_the_backend_names_are_all_worded() -> None:
    assert {"unsettled:" + reason for _text, reason in CHECKS} <= set(table())


def test_the_page_prints_its_codes_through_the_table() -> None:
    for name in ("rail.js", "result.js", "ui.js"):
        assert "words.js" in (PAGE / name).read_text(), name
