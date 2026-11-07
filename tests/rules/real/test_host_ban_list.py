"""HOSTBAN: the converted-stage list only grows, judged against the merge base with origin/main (tests/rules/host_ban.py)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rules.host_ban import CONTRACT, ROOT, converted


def test_the_list_only_grows():
    ran = subprocess.run(["git", "-C", str(ROOT), "show", "origin/main:.importlinter"], capture_output=True, text=True, check=False)
    if ran.returncode != 0:
        pytest.skip("no origin/main to compare with")
    before = converted(ran.stdout) if CONTRACT in ran.stdout else []
    assert set(before) <= set(converted()), f"stages left the converted list: {sorted(set(before) - set(converted()))}"
