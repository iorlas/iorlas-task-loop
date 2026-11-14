"""Public refusal coverage follows the producers, and asserts actual human presentation."""


from pathlib import Path

import pytest
import refusal_inventory
from refusal_inventory import DYNAMIC_REASONS, REVIEWED_DYNAMIC, census, typed_reasons

from taskloop.hold_guide import pending_guide
from taskloop.inspection_guide import CONFIG, PROFILE
from taskloop.land_guide import CANDIDATE_RELEASE, LAND_GUIDE
from taskloop.machine_config import ConfigRefused, Refusal
from taskloop.operations import Ended, Failed, Move, Round, refused_config
from taskloop.result_data import as_data
from taskloop.step_guide import CHECKS_GUIDE, GUIDE, refusal_guide
from taskloop.step_render import human

LITERALS, DYNAMIC = census()
CASES = sorted(LITERALS | {("step", word) for word in typed_reasons() | DYNAMIC_REASONS})


def test_dynamic_forwarding_has_an_explicit_reviewed_upstream_domain() -> None:
    assert DYNAMIC == REVIEWED_DYNAMIC


@pytest.mark.parametrize("context,reason", CASES)
@pytest.mark.parametrize("detail", ["", "arbitrary detail mentioning `tl step release --abandon`"])
def test_every_public_reason_renders_explanation_and_action(context: str, reason: str, detail: str) -> None:
    result = Failed("refused", reason, detail)
    lines = human(f"tl step {context if context == 'land' else 'start'}", result, None)
    expected = refusal_guide(reason, land=context == "land")
    assert expected in lines and len(expected.split()) >= 6
    assert as_data(result)["error"] == {"kind": "refused", "reason": reason, "message": detail or None}


def test_a_removed_guide_and_a_new_producer_reason_fail_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(GUIDE, "label")
    with pytest.raises(KeyError):
        human("tl step next", Failed("refused", "label"), None)
    for reason in ("new_reason_without_a_guide", "environment:new_reason", "answer:new_reason", "run:new_reason"):
        with pytest.raises(KeyError):
            human("tl step start", Failed("refused", reason), None)


@pytest.mark.parametrize("reason", ["missing", "unknown_key"])
def test_config_and_profile_collisions_have_different_remedies(reason: Refusal) -> None:
    result = refused_config(ConfigRefused(reason, "detail"))
    assert CONFIG[reason] in human("tl step show", result, None)
    assert PROFILE[reason] not in human("tl step show", result, None)


def test_checks_land_and_candidate_release_keep_their_overrides() -> None:
    assert CHECKS_GUIDE["unsettled"] in human("tl step release", Failed("unsettled", "unsettled", checks=True), None)
    assert LAND_GUIDE["expired"] in human("tl step land", Failed("refused", "expired"), None)
    assert CANDIDATE_RELEASE["entry_running"] in human(
        "tl step release", Failed("refused", "entry_running", land=True), None)


@pytest.mark.parametrize("word", ["refused:label", "unavailable:store", "refused:conflict", "unusable:s1:dirty"])
def test_rounds_and_end_results_do_not_omit_reasons_or_request_cli_actions(word: str) -> None:
    result = Round("tasks", (Move("tl-1", "land", word),), "")
    lines = human("tl step next", result, None)
    assert len(lines) >= 2 and all("`tl " not in line and "`bd " not in line for line in lines)
    ended = human("tl step rounds", Ended("tasks", word, "arbitrary detail"), None)
    assert len(ended) >= 3 and "`tl " not in ended[-1]


@pytest.mark.parametrize("word", ["held:slot_dirty", "unavailable:observe", "unsettled:check_running", "refused:landed"])
def test_pending_holds_name_the_situation_and_decision_in_words(word: str) -> None:
    text = pending_guide(f"pending implement {word}")
    assert len(text.split()) >= 8 and "`tl " not in text and "`bd " not in text


@pytest.mark.parametrize("context,reason", CASES)
def test_forwarded_round_refusals_have_reason_guidance_without_cli_requests(context: str, reason: str) -> None:
    result = Round("tasks", (Move("tl-1", "land" if context == "land" else "advance", f"refused:{reason}"),))
    lines = human("tl step next", result, None)
    assert len(lines) >= 2 and "`tl " not in lines[-1] and "`bd " not in lines[-1]


def test_a_new_literal_producer_fails_until_it_has_a_guide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "new_operation.py"
    source.write_text('def operation():\n    return Failed("refused", "new_producer_reason")\n')
    monkeypatch.setattr(refusal_inventory, "ROOT", tmp_path)
    cases, _dynamic = refusal_inventory.census()
    assert cases == {("step", "new_producer_reason")}
    for _context, reason in cases:
        with pytest.raises(KeyError):
            human("tl step start", Failed("refused", reason), None)
