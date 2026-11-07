"""Profile validation and slot folder facts without setup presentation types."""
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
