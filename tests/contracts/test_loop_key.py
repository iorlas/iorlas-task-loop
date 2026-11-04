"""One repo has one loop key however its path is spelled: git answers real paths, and a symlinked spelling (macOS /var is /private/var)
must not give the same checkout a second key (tl-5gzj)."""

import support.paths  # noqa: F401

# isort: split
from taskloop.contracts.ids import loop_key


def test_a_symlinked_spelling_of_a_repo_path_has_the_key_of_its_real_path(tmp_path):
    parent = tmp_path / "real"
    (parent / "repo").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(parent, target_is_directory=True)
    assert loop_key(str(link / "repo")) == loop_key(str(parent / "repo"))
    assert loop_key(str(parent / "repo")).startswith("repo-")


def test_a_path_that_does_not_exist_keeps_its_own_key():
    assert loop_key("/repos/lifesim") != loop_key("/repos/task-loop")
    assert loop_key("/repos/lifesim").startswith("lifesim-")
