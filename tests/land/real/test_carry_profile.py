"""The closure of this repo's gate check (dev/affected.py --closure), read from the real checkout: the files a change's tests depend on,
so a pass carries over a base move that touched none of them."""
from pathlib import Path

import support.paths  # noqa: F401
from affected import Repo, closure, select

ROOT = Path(__file__).resolve().parents[3]


def test_the_closure_lists_the_files_a_change_depends_on():
    repo = Repo(ROOT)
    listed = closure(repo, select(repo, {"src/taskloop/app/land/carry.py"}))
    assert "src/taskloop/app/land/carry.py" in listed and "tests/land/test_carry.py" in listed
