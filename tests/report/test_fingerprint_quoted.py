"""A quoted payload keeps a short hash of its own text: distinct causes stay apart, the same cause with other ids collides."""

import pytest

from taskloop.domain.report import matchers


@pytest.mark.parametrize(("a", "b", "same"), [
    ('failed: "authentication expired"', 'failed: "quota exhausted"', False),
    ("failed: `authentication expired`", "failed: `quota exhausted`", False),
    ('failed: "authentication expired"', "failed: 'authentication expired'", True),
    ('failed: "bead tl-12 broke at /a/b/c.py"', 'failed: "bead tl-99 broke at /x/y/z.py"', True),
    ("failed: no quotes here", "failed: no quotes here", True),
])
def test_quoted_text_separates_distinct_causes(a: str, b: str, same: bool) -> None:
    assert (matchers.fingerprint(a) == matchers.fingerprint(b)) is same
    assert (matchers.fingerprint_head(a) == matchers.fingerprint_head(b)) is same


def test_the_slug_stays_readable_and_empty_stays_empty() -> None:
    assert matchers.fingerprint('failed: "x"').startswith("failed: quoted")
    assert matchers.fingerprint("") == "" and matchers.fingerprint(None) == ""
