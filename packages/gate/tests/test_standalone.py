"""Standalone selection and rendering keep the CLI's exact output and ordering."""
import argparse
from unittest.mock import Mock, patch

import pytest
from tlkernel.checks import CheckResult
from tlkernel.config import load
from tlkernel.ids import CheckId

from tlgate import authorization, checklog


def registry():
    return load({"engine": {"checks": [
        {"id": "unit", "argv": ["true"], "run": "gate"},
        {"id": "stage", "argv": ["false"], "run": "stage"},
    ]}}).engine


def test_named_selection_preserves_order_and_deduplicates():
    assert [c.id for c in checklog.chosen(registry(), ["stage", "unit", "stage"])] == ["stage", "unit"]


def test_missing_selection_names_registry_in_its_original_order():
    with pytest.raises(SystemExit) as error:
        checklog.chosen(registry(), ["missing", "other"])
    assert str(error.value) == "tl check: not in the registry: missing, other (tl check --list: unit, stage)"


@pytest.mark.parametrize(("status", "cached", "exit_code", "state"), [
    ("skipped", True, 0, "skipped (no changes)"),
    ("unverified", True, 0, "UNVERIFIED"),
    ("passed", True, 0, "cached"),
    ("passed", False, 0, "ok"),
    ("failed", False, 1, "FAILED"),
])
def test_step_output(status, cached, exit_code, state):
    result = CheckResult(id=CheckId("unit"), cmd="true", group="tests", status=status,
                         cached=cached, exit=exit_code, why="no changes", secs=2.6)
    assert checklog.step_line(result) == f"{'unit':<24} {state:<30}     3s"


def test_list_precedes_conflicting_file_options_and_never_opens_checkout():
    workspace, save, checker = Mock(), Mock(), Mock()
    args = argparse.Namespace(list=True, staged=True, all=True, base_commit=None)
    with patch("builtins.print") as output:
        assert checklog.standalone(args, profile=registry, workspace=workspace, save=save, checker=checker) == 0
    output.assert_called_once_with(
        "unit  run=gate  group=tests  when=-  true\n"
        "stage  run=stage  group=tests  when=-  false"
    )
    workspace.assert_not_called()
    save.assert_not_called()
    checker.assert_not_called()


def test_bound_policy_skips_both_profile_readers():
    cfg, working, committed = registry(), Mock(), Mock()
    assert authorization.selected_profile(cfg, "commit", working, committed) is cfg
    working.assert_not_called()
    committed.assert_not_called()
