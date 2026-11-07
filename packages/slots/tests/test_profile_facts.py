"""Profile validation and slot folder facts without setup presentation types."""
import contextlib
import io
import json
from pathlib import Path

from tlslots import profile_facts


def test_profile_problems_and_configured_slot_folders(tmp_path: Path):
    profile = tmp_path / ".task-loop.json"
    assert profile_facts.profile_problem(profile)
    assert profile_facts.slot_folders(tmp_path) is None
    profile.write_text(json.dumps({"slots": {"cuont": 2}}))
    assert "cuont" in profile_facts.profile_problem(profile)
    assert profile_facts.slot_folders(tmp_path) is None
    profile.write_text(json.dumps({"slots": {"count": 0}}))
    assert profile_facts.profile_problem(profile) == ""
    assert profile_facts.slot_folders(tmp_path) is None
    profile.write_text(json.dumps({"slots": {"count": 3, "dir": "worktrees"}}))
    root = tmp_path / "worktrees"
    (root / "s2").mkdir(parents=True)
    assert profile_facts.slot_folders(tmp_path) == profile_facts.SlotFolders(3, root, ("s1", "s3"))


def test_file_validation_keeps_falsey_json_defaults_and_captures_config_exit(tmp_path):
    profile = tmp_path / '.task-loop.json'
    profile.write_text('[]')
    assert profile_facts.profile_problem(profile) == ''
    assert profile_facts.slot_folders(tmp_path) is None
    profile.write_text('{"slots": {"cuont": 2}}')
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        problem = profile_facts.profile_problem(profile)
    assert problem.startswith('task-loop: the repo profile: ')
    assert 'cuont' in problem
    assert err.getvalue() == ''
    profile.write_text('{')
    assert 'Expecting property name' in profile_facts.profile_problem(profile)
