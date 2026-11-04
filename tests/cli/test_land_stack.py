"""`tl land-stack` arguments: an item is a PR number, a pull url or a branch; --bead and --supersede are keyed by the item text."""
import sys
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl_main

# isort: split
from taskloop.cli.land_stack import item_of, pairs


class Items(Case):
    def test_a_number_a_url_and_a_branch(self):
        assert (item_of("12", {}, {}).pr, item_of("12", {}, {}).branch) == (12, "")
        assert item_of("https://github.com/o/r/pull/34/", {}, {}).pr == 34
        b = item_of("task/x", {"task/x": "tl-1"}, {"task/x": "9"})
        assert (b.branch, b.pr, b.bead, b.supersedes) == ("task/x", 0, "tl-1", 9)

    def test_a_pair_without_a_value_is_refused(self):
        with pytest.raises(SystemExit):
            pairs(["task/x"], "--bead")

    def test_the_verb_is_registered_and_has_help(self):
        r = tl_main("land-stack", "--help", cwd=".")
        assert r.returncode == 0
        assert "--supersede" in r.stdout
        assert "checkout of the branch tree" in " ".join(r.stdout.split())
        assert "hook gates the checked-out tree" in " ".join(r.stdout.split())
