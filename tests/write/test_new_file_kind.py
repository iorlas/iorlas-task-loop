"""Which untracked files a stage meant: a pure function of the ignore globs, the files accepted so far and the plan (tl-bxk.10.24)."""
import pytest

from taskloop.domain.write.newfiles import new_file_kind

PLAN = {"stages": [{"files": ["src/a.py", "./docs/", "pkg/*.cfg", ".", "  lib/x.txt  "]}]}


@pytest.mark.parametrize(("path", "kind"), [
    ("notes.log", "ignored"),                 # an engine.untracked_ignore glob
    (".task/t-1/brief.md", "ignored"),        # the scratch folder
    ("src/a.py", "meant"),                    # listed in a stage
    ("docs/guide/new.md", "meant"),           # under a listed folder
    ("pkg/one.cfg", "meant"),                 # matches a listed glob
    ("lib/x.txt", "meant"),                   # a listed file, spaces trimmed
    ("src/b.py", "unexplained"),
    ("accepted.dat", "meant"),                # a review accepted it
    ("accepted.dat.meta", "meant"),           # a .meta follows its file
    ("other.dat.meta", "unexplained"),
    ("sub\\notes.log", "ignored"),            # a backslash path is normalised first (fnmatch: * crosses /)
])
def test_the_kind_of_a_new_file(path, kind):
    assert new_file_kind(path, ["*.log"], ["accepted.dat"], PLAN) == kind


def test_a_run_with_no_plan_and_nothing_accepted_means_nothing():
    assert new_file_kind("src/a.py", [], [], None) == "unexplained"
