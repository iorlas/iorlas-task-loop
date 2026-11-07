"""dev/killpoints.py's verdict: what the world file may hold after a kill and a resume."""
import importlib.util
import sys

import support.paths

spec = importlib.util.spec_from_file_location("killpoints", support.paths.ROOT / "dev" / "killpoints.py")
assert spec is not None and spec.loader is not None
killpoints = importlib.util.module_from_spec(spec)
sys.modules["killpoints"] = killpoints
spec.loader.exec_module(killpoints)

NAMES = ["a", "b", "c"]


def test_each_effect_once_in_order_holds():
    assert killpoints.verdict(NAMES, ["a", "b", "c"], 1, "before") == ""


def test_the_effect_killed_after_it_ran_and_before_its_key_may_appear_twice():
    assert killpoints.verdict(NAMES, ["a", "b", "b", "c"], 1, "after_effect") == ""


def test_a_repeat_of_any_other_effect_is_a_failure():
    assert "more than once" in killpoints.verdict(NAMES, ["a", "a", "b", "c"], 1, "after_effect")
    assert "more than once" in killpoints.verdict(NAMES, ["a", "b", "b", "c"], 1, "after_mark")


def test_a_missing_effect_and_a_wrong_order_are_failures():
    assert "never applied: c" in killpoints.verdict(NAMES, ["a", "b"], 1, "before")
    assert "order" in killpoints.verdict(NAMES, ["b", "a", "c"], 1, "before")


def test_the_dropped_checkpoint_has_no_key_to_lose_so_it_may_not_repeat():
    assert "more than once" in killpoints.verdict(["a", "drop_checkpoint"], ["a", "drop_checkpoint", "drop_checkpoint"], 1, "after_effect")
