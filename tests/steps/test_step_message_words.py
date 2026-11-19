"""Step outcomes explain retained state and owner decisions without command recipes."""

from pathlib import Path

import pytest

from taskloop.attempt_store import AttemptKey
from taskloop.check_status import HALF_DONE
from taskloop.launch import LaunchUncertain
from taskloop.operations import UNCLAIMING, Ended, Failed, ReleasedTask, Started, launched, require_database
from taskloop.rounds_lock import RoundsRunning
from taskloop.slot_release import Released
from taskloop.step_guide import ABANDON, CHECKS_GUIDE, GUIDE, HELD, NEEDS_OWNER, PUBLISH, ROUNDS, STEP_ONLY, discard, guide
from taskloop.step_render import SLOT_COUNT_NOTE, human

# Imported land and hold explanations belong to the sibling task's message producers.
STEP_WORDS = sorted(GUIDE.keys() - {"land", "landed", "landing", "hold", "on_hold"})
RECIPES = ("tl step ", "tl slot ", "tl profile ", "bd ", "git push", "git switch", "git fetch", "ps -", "lsof -", "kill -")


@pytest.mark.parametrize("word", STEP_WORDS)
def test_step_guidance_has_words_instead_of_command_recipes(word: str) -> None:
    text = guide(word, checks=False)
    assert len(text.split()) >= 6
    assert all(recipe not in text for recipe in RECIPES)


@pytest.mark.parametrize("word", sorted(CHECKS_GUIDE))
def test_checks_render_their_own_situation_and_decision(word: str) -> None:
    lines = human("tl step start", Failed("refused", word, checks=True), None)
    assert guide(word, checks=True) in lines
    assert all(recipe not in line for line in lines[1:] for recipe in RECIPES)


@pytest.mark.parametrize("text", [STEP_ONLY, PUBLISH, HELD, ABANDON, ROUNDS, NEEDS_OWNER, HALF_DONE, UNCLAIMING, SLOT_COUNT_NOTE])
def test_shared_step_explanations_have_no_recipes(text: str) -> None:
    assert len(text.split()) >= 6
    assert all(recipe not in text for recipe in RECIPES)


@pytest.mark.parametrize("checks", [False, True])
def test_overdue_process_guidance_requires_identity_proof_and_preserves_stop_order(checks: bool) -> None:
    text = guide("stuck:hung", checks=checks)
    assert "identity" in text and "slot working directory" in text
    assert "only confirmed owned processes" in text
    assert ("check groups first and then the entry" if checks else "worker first and then the entry") in text


def test_retry_limits_and_claim_boundaries_remain_explicit() -> None:
    assert "repeated twice" in GUIDE["repeats_exhausted"]
    assert "Setup failed twice" in GUIDE["stuck:setup_failed"]
    assert "Two consecutive counted refusals" in CHECKS_GUIDE["start"]
    assert "past it every round's relaunch counts" in CHECKS_GUIDE["start"]
    assert "three consecutive changes" in GUIDE["main_moved"]
    assert "nothing retakes the claim" in GUIDE["start"]
    assert "not retried automatically" in GUIDE["done"]
    assert "compare" in PUBLISH and "never forces" in PUBLISH


@pytest.mark.parametrize("reason", ["not_committed", "read_only", "dirty", "uncommitted", "session_pending",
                                  "branch", "unborn", "changed_answer", "not_advanceable", "plan_empty"])
def test_completion_refusals_name_factory_commit(reason: str) -> None:
    text = " ".join(human("tl step commit", Failed("refused", reason), None))
    assert "factory commit" in text.lower()
    assert "verify" not in text.lower() and "verification" not in text.lower()


def test_started_and_failed_launches_render_progress_and_observation_decisions() -> None:
    started = Started("started", "tasks", "tl-1", "attempt", False)
    lines = human("tl step start", started, None)
    assert HELD in lines and STEP_ONLY in lines and "retained evidence" in lines[-1]
    assert all(recipe not in line for line in lines for recipe in RECIPES)
    key = AttemptKey("attempt", "dispatch", 1)
    uncertain = launched(LaunchUncertain(key, (7, "start", "boot")), "tasks", "tl-1", key, existing=True)
    assert isinstance(uncertain, Failed) and uncertain.word == "uncertain:launch"
    lines = human("tl step start", uncertain, None)
    assert "Confirm its identity" in lines[1]
    admitted = human("tl step start", Failed("unavailable", "start", admitted=True), None)
    assert "Inspect the registered entry" in admitted[-1]
    assert all(recipe not in line for line in [*lines[1:], *admitted[1:]] for recipe in RECIPES)


def test_missing_database_explains_initialization_without_prescribing_a_command() -> None:
    result = require_database(lambda: None)
    assert isinstance(result, Failed) and result.word == "refused:database"
    lines = human("tl step start", result, None)
    assert "slot adoption initializes it" in lines[1]
    assert all(recipe not in line for line in lines[1:] for recipe in RECIPES)


def test_abandon_and_interrupted_rounds_render_the_remaining_decision() -> None:
    result = ReleasedTask("tasks", "tl-1", "attempt", Released("s1", None, True, "not_held", True))
    lines = human("tl step release", result, None)
    assert "Inspect tracker ownership" in lines[-2]
    assert "next approved admission starts a fresh attempt" in lines[-1]
    stopped = human("tl rounds start", Ended("tasks", "interrupted"), None)
    assert "Launched steps keep running" in stopped[0] and "restarting scheduling continues them" in stopped[0]
    assert all(recipe not in line for line in [*lines, *stopped] for recipe in RECIPES)


@pytest.mark.parametrize("pid", [None, 42])
def test_scheduler_ownership_names_the_holder_without_a_recipe(pid: int | None) -> None:
    text = str(RoundsRunning(pid))
    assert "Another scheduling process owns this backlog" in text
    assert ("pid 42" in text) == (pid is not None)
    assert all(recipe not in text for recipe in RECIPES)


def test_discard_explains_order_scope_and_conditional_claim_return() -> None:
    text = discard(Path("/factory/factory.db"))
    assert "owner may decide" in text and "independently verified process identities" in text
    assert text.index("First stop scheduling") < text.index("Only after all are stopped, discard /factory/factory.db")
    assert "-wal/-shm" in text and "preserve every other factory's database" in text
    assert "only if it is still held by the factory" in text and "inspect and readopt each slot worktree" in text
    assert all(recipe not in text for recipe in RECIPES)
