"""Effective slot defaults and provenance use the selected profile, including empty tables."""
import json
from unittest.mock import Mock, patch

import pytest

from taskloop.app.doctor import setup
from taskloop.app.doctor.setup_checks import slot_warnings
from taskloop.app.wire import brief
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.slots import SlotTable
from tlslots import profile_facts
from tlslots.config import cfg_source, profile_slots, selected_profile


@pytest.mark.parametrize("text,count", [("{", 0), ("{}", 4)])
def test_working_profile_slots_read_failure_keeps_slots_off(tmp_path, text, count):
    (tmp_path / ".task-loop.json").write_text(text)
    assert profile_slots(str(tmp_path), git=None).count == count


@pytest.mark.parametrize("data,count,source", [
    ({}, 4, "default"),
    ({"slots": {}}, 4, "default"),
    ({"slots": {"count": 0}}, 0, "profile"),
    ({"slots": {"count": 3}}, 3, "profile"),
])
def test_effective_slots_in_config_status_and_doctor(data, count, source):
    git = Mock(spec=Git)
    git.rev_parse.return_value = "abc123"
    git.show.return_value = json.dumps(data)
    # Local count differs: provenance must come from the selected committed dict.
    with patch("tlslots.config.profile", return_value={"slots": {"count": 7}}):
        selected = selected_profile("/repo", git)
        assert (selected.cfg.slots.count, selected.slots_source) == (count, source)
        assert cfg_source("/repo", git) == (selected.cfg, selected.base, selected.commit)
        table = SlotTable(configured=count, source="origin/main", slots=[])
        with patch.object(brief.wslots, "slot_table", return_value=table):
            lines = brief.slot_lines("/repo", Identity(actor="owner", home="."), 0, git)
        assert f"slots: {count} ({source})" in lines
        doctor, warnings = slot_warnings(lambda: table, None, lambda _: [],
                                        (selected.cfg.slots.count, selected.slots_source))
        assert doctor.startswith(f"slots: {count} ({source}) configured")
        assert warnings == []


def test_default_slots_setup_requires_four_folders(tmp_path):
    (tmp_path / ".task-loop.json").write_text("{}")
    plan = setup.repo_part(tmp_path, profile_facts)
    slots = next(check for check in plan.checks if check.id == "slots")
    assert not slots.ok
    assert [fix.id for fix in plan.fixes] == ["slots"]
    for name in ("s1", "s2", "s3", "s4"):
        (tmp_path / ".slots" / name).mkdir(parents=True)
    done = setup.repo_part(tmp_path, profile_facts)
    assert next(check for check in done.checks if check.id == "slots").ok
    assert done.fixes == []
