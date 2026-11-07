"""Is a bead visual: the planner's case classes decide (domain/work/visual.py); visual_paths is only a check; `show` items are
checked against the artifacts the stage attempt registered."""

from tltestkit.case import Case
from tlwork.work import visual as v


def case(cls: str, **kw: object) -> dict[str, object]:
    return {"criterion": f"a {cls} criterion", "check": None, "class": cls, **kw}


class IsVisual(Case):
    def test_no_case_or_only_test_cases_is_not_visual(self):
        assert not v.is_visual([])
        assert not v.is_visual([case("test"), {"criterion": "no class given", "check": None}])

    def test_a_look_objective_taste_or_show_case_makes_the_bead_visual(self):
        for cls in ("look-objective", "taste", "show"):
            assert v.is_visual([case("test"), case(cls)]), cls


class VisualPathsCheck(Case):
    def test_a_hit_that_is_not_excluded_counts(self):
        assert v.touches_visual_path(["web/a.js"], ["web/**"], ["web/tests/**"])

    def test_an_excluded_or_unlisted_path_does_not(self):
        assert not v.touches_visual_path(["web/tests/a.js"], ["web/**"], ["web/tests/**"])
        assert not v.touches_visual_path(["src/a.py"], ["web/**"], [])


class UnmetShows(Case):
    SHOW = case("show", shows=[{"name": "board.png", "role": "after"}, {"name": "old.png", "role": "before"}])

    def test_every_named_artifact_present_is_met(self):
        assert v.unmet_shows([self.SHOW], {("board.png", "after"), ("old.png", "before")}) == []

    def test_a_missing_name_or_a_wrong_role_is_named(self):
        got = v.unmet_shows([self.SHOW], {("board.png", "result")})
        assert len(got) == 1 and "board.png (role after)" in got[0] and "old.png (role before)" in got[0]

    def test_other_classes_and_a_show_that_names_nothing_are_never_a_miss(self):
        assert v.unmet_shows([case("test"), case("show"), case("taste", shows=[{"name": "x.png", "role": "after"}])], set()) == []


class NamesCriterion(Case):
    AC = "- the parser rejects a bad key with a clear message\n- the dashboard lists every slot"

    def test_an_item_that_restates_a_criterion_names_it(self):
        assert v.names_criterion("whether the parser rejects a bad key with a clear message", self.AC)

    def test_an_unrelated_item_does_not(self):
        assert not v.names_criterion("the retry delay was not measured on a slow disk", self.AC)

    def test_a_short_item_never_does(self):
        assert not v.names_criterion("parser key", self.AC)
