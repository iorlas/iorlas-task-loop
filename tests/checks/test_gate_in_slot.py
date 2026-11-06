"""engine.gate_tree "slot": the land gate runs in the committed slot under guards, and its passes are the fix rounds' passes."""
from types import SimpleNamespace
from unittest import mock

import pytest
from support.cfgs import cfg_with

from taskloop.app.checks import runner
from taskloop.app.checks.clean import guard_slot
from taskloop.app.checks.host import CheckFault
from taskloop.contracts.checks import CheckFaultKind
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import TreeSha


def host(ignored: list[str], cfg: EngineConfig | None = None, tree: str = "t", head_tree: str = "t") -> SimpleNamespace:
    git = mock.Mock()
    git.rev_parse.side_effect = lambda d, rev: head_tree if rev == "HEAD^{tree}" else "head"
    git.ls_files.return_value = ignored
    return SimpleNamespace(wt="slot", git=git, cfg=cfg or EngineConfig(), checkout=SimpleNamespace(tree_hash=lambda: tree))


def test_a_committed_slot_without_ignored_sources_passes_the_guard():
    guard_slot(host([".venv/lib/x.py", "node_modules/a/b.json", "build.log"]))


def test_an_uncommitted_slot_is_refused_as_dirty():
    with pytest.raises(CheckFault) as fault:
        guard_slot(host([], tree="dirty"))
    assert fault.value.kind == CheckFaultKind.DIRTY_SLOT


@pytest.mark.parametrize("path", ["src/secret.py", "Assets/Gen/Table.cs", "config/local.yaml", "data.json"])
def test_an_ignored_source_file_outside_the_allowlist_is_refused_by_name(path):
    with pytest.raises(CheckFault) as fault:
        guard_slot(host([path, ".venv/lib/ok.py"]))
    assert fault.value.kind == CheckFaultKind.DIRTY_SLOT
    assert path in fault.value.text and ".venv" not in fault.value.text


@pytest.mark.parametrize("path", [".import_linter_cache/delegate.meta.json", ".mypy_cache/3.13/x.data.json", ".ruff_cache/0.1/y.json",
                                  "pkg/.pytest_cache/v/cache/nodeids.json"])
def test_the_tool_caches_of_the_default_allowlist_are_not_source(path):
    guard_slot(host([path]))


def test_the_repo_declares_its_own_allowlist():
    cfg = cfg_with(gate_ignored_allow=["generated/**"])
    guard_slot(host(["generated/Table.cs"], cfg))


def slot_cfg(tree: str) -> EngineConfig:
    return cfg_with(gate_tree=tree, checks=[{"id": "t", "argv": ["true"], "run": "gate"}])


class Stop(Exception):
    pass


@pytest.mark.parametrize(("tree", "keys_clean"), [("clean", True), ("slot", False)])
def test_the_delivery_question_reads_the_keys_of_where_the_gate_ran(tree, keys_clean):
    git = mock.Mock()
    git.rev_parse.return_value = "b"
    git.merge_base.return_value = "b"
    with mock.patch.object(runner, "InputKeys", side_effect=Stop) as keys, pytest.raises(Stop):
        runner.cached_gate(slot_cfg(tree), git, "wt", mock.Mock(), mock.Mock(), TreeSha("tree"), None, clean=True)
    assert keys.call_args.kwargs["clean"] is keys_clean


@pytest.mark.parametrize(("tree", "isolated_runs", "guarded"), [("clean", 1, 0), ("slot", 0, 1)])
def test_the_land_gate_enters_a_fresh_checkout_or_the_guarded_slot(tree, isolated_runs, guarded):
    box = SimpleNamespace(cfg=slot_cfg(tree))
    with mock.patch.object(runner, "isolated", side_effect=Stop) as fresh, mock.patch.object(runner, "guard_slot") as guard, \
            mock.patch.object(runner.Checker, "_history", side_effect=Stop), pytest.raises(Stop):
        runner.Checker(box).run_items([], clean=True)
    assert (fresh.call_count, guard.call_count) == (isolated_runs, guarded)
