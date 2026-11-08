"""tltestkit.limits: the kind of a test by path, the limit of each kind."""
import pytest

from tltestkit.limits import LIMITS_S, hang_s, kind_of_parts, limit_for, verdict


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


@pytest.mark.parametrize(("first", "second"), [(0.2, None), (0.2, 0.3), (2.1, 0.2)])
def test_budget_passes_without_retry_when_a_measurement_is_under(first, second):
    assert verdict(first, second, 2.0) == (False, None)


def test_budget_requests_one_retry_then_names_both_over_measurements():
    assert verdict(2.1, None, 2.0) == (True, None)
    retry, message = verdict(2.1, 2.2, 2.0)
    assert not retry
    assert message == "took 2.10 s and 2.20 s of work on two runs, both over its 2.00 s limit"
