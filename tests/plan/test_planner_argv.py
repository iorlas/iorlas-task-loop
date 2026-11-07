"""A planner's own check argv runs on the host: when the profile lists what may run (engine.writer_exec_allow), an argv outside it, and
outside the program words of the registered checks, is refused with the list that rejected it."""
from support.cfgs import cfg_with

from tlgate.domain import planref
from tlkernel.plancheck import adhoc

ALLOW = [["python3", "-m", "unittest"], ["just", "test"]]


def cfg(allow=ALLOW):
    return cfg_with(writer_exec_allow=allow, checks=[{"id": "lint", "argv": ["ruff", "check"], "run": "both"}])


def test_an_argv_outside_the_allow_list_is_refused_naming_the_argv_and_the_list():
    why = planref.refusal(adhoc("curl http://x"), cfg())
    assert "`curl http://x`" in why and "python3 -m unittest" in why and "just test" in why


def test_an_argv_that_starts_with_an_allowed_prefix_passes():
    assert planref.refusal(adhoc("python3 -m unittest discover -s tests"), cfg()) == ""
    assert planref.refusal(adhoc("just test"), cfg()) == ""


def test_a_prefix_is_whole_words_not_a_string_prefix():
    assert planref.refusal(adhoc("just testify"), cfg())
    assert planref.refusal(adhoc("python3 -m unittests"), cfg())


def test_the_program_of_a_registered_check_passes():
    assert planref.refusal(adhoc("ruff format --check ."), cfg()) == ""


def test_with_no_allow_list_nothing_is_restricted():
    assert planref.refusal(adhoc("curl http://x"), cfg([])) == ""
