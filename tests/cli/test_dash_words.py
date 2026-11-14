"""The page's one table of words for typed codes (`words.js`): the codes the data shapes carry are all in it, so none shows raw."""

import re
from pathlib import Path

import pytest

from taskloop.dash_verify import CHECKS

PAGE = Path(__file__).resolve().parents[2] / "src/taskloop/dash/static"
REQUIRED = (
    "needs_owner", "failed:needs_owner", "answer:schema_invalid", "failed:answer:schema_invalid", "failed:test:failed", "held:slot_dirty",
    "verified", "reused", "unsettled:branch", "unsettled:unsafe", "unsettled:ignored", "unsettled:uncommitted", "unsettled:rejected",
    "pending", "registered", "passed", "verification", "unsafe", "uncommitted", "ignored", "branch", "rejected", "repeat", "failed_check",
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


@pytest.mark.parametrize("code,expected", [
    ("verification", "The factory's check of the answer failed"),
    ("unsafe", "A listed path is unsafe"),
    ("unsettled:unsafe", "Not committed: a listed path is unsafe"),
    ("unsettled:rejected", "Not committed: the commit broke a rule"),
])
def test_repeat_causes_and_verification_failures_have_readable_words(code: str, expected: str) -> None:
    assert table()[code] == expected


def test_rejected_rules_and_check_repeat_reasons_keep_their_specific_tail() -> None:
    source = (PAGE / "words.js").read_text()
    families = dict(re.findall(r'\["([^"\n]+)", "([^"\n]+)"\]', source))
    assert families["rejected:"] == families["failed:rejected:"] == "Not committed: the commit broke a rule: "
    assert families["test:"] == families["failed:test:"] == "Checks failed: "
    assert families["run:"] == families["failed:run:"] == "The agent attempt failed: "


@pytest.mark.parametrize("code,label", [
    ("waiting", "Waiting"), ("checks", "Check"), ("held", "Hold"),
    ("succeeded", "Success"), ("failed", "Failure"),
])
def test_serialized_states_keep_their_codes_and_use_glossary_labels(code: str, label: str) -> None:
    source = (PAGE / "ui.js").read_text()
    assert re.search(rf'(?:id: "{code}",|{code}: \{{) label: "{label}"', source)


@pytest.mark.parametrize("name", ["ui.js", "app.js", "drawer.js", "rail.js", "result.js", "taskview.js", "lines.js"])
def test_owned_labels_do_not_use_the_retired_execution_and_status_words(name: str) -> None:
    source = (PAGE / name).read_text()
    assert not re.search(r'\b(?:try \$\{|Try again|Trying again|Quiet \$\{)', source), name
    assert not re.search(r'label: "(?:Ready|Checks|Held|Succeeded|Failed)"', source), name


def test_waiting_and_activity_labels_describe_observations_rather_than_readiness_or_health() -> None:
    source = (PAGE / "ui.js").read_text()
    assert "Tasks with no current work, including queued and abandoned tasks." in source
    assert "Last activity ${fmtDur(s * 1000)} ago" in source
    assert 'waiting: ["", " waiting"]' in (PAGE / "app.js").read_text()
    assert '"Reload task"' in (PAGE / "taskview.js").read_text()
