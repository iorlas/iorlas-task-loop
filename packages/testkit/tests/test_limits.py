"""tltestkit.limits: the kind of a test by path, the limit of each kind."""
import pytest
from tltestkit.limits import LIMITS_S, hang_s, kind_of_parts, limit_for


@pytest.mark.parametrize(("parts", "marked", "kind"), [
    (("land", "test_x.py"), False, "logic"),
    (("land", "real", "test_x.py"), False, "real"),
    (("land", "test_x.py"), True, "real"),
    (("e2e", "test_flow.py"), False, "e2e"),
    (("live", "test_scenario.py"), True, "live"),
    (("real_estate", "test_x.py"), False, "logic"),
])
def test_the_kind_comes_from_the_path(parts, marked, kind):
    assert kind_of_parts(parts, marked_real=marked) == kind


def test_a_rules_test_gets_the_rules_floor_and_a_module_may_ask_for_more():
    assert limit_for("logic") == LIMITS_S["logic"]
    assert limit_for("logic", rules=True) == 15.0
    assert limit_for("logic", module_limit=40.0) == 40.0


def test_a_test_is_hung_after_the_scaled_wall_limit_or_ten_times_its_own():
    assert hang_s(2.0) == 300.0
    assert hang_s(2.0, scale=2) == 600.0
    assert hang_s(100.0) == 1000.0
