"""AC parsing (tl-9un.1): which commands an acceptance names, and which of them a repo profile registers. Pure functions."""
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.domain.beads import matchers as acnames

REG = [("unit", ["pytest", "-q"]), ("lint", ["ruff", "check"])]


class Commands(Case):
    def test_a_backticked_command_with_arguments_is_named(self):
        got = acnames.commands("- `pytest -q` passes\n- `foo --bar baz` prints ok")
        assert [c.argv for c in got] == [["pytest", "-q"], ["foo", "--bar", "baz"]]

    def test_prose_code_and_paths_are_not_commands(self):
        text = "- `src/a.py` has `def f(x)` and `async def g`\n- `Blocked` is raised when `x = 1`\n- a plain sentence"
        assert acnames.commands(text) == []

    def test_a_dollar_line_and_a_relative_program_are_commands(self):
        got = acnames.commands("$ make all\n- `./run.sh --fast` exits 0")
        assert [c.argv for c in got] == [["make", "all"], ["./run.sh", "--fast"]]

    def test_a_single_word_is_named_only_when_the_profile_registers_it(self):
        text = "- `unit` is green\n- `thing` is green"
        got = acnames.commands(text, ids={"unit"})
        assert [c.argv for c in got] == [["unit"]]

    def test_the_same_command_twice_is_named_once(self):
        assert len(acnames.commands("- `pytest -q` a\n- `pytest -q` b")) == 1


class Registered(Case):
    def test_by_id_or_by_exact_argv(self):
        named = acnames.commands("- `unit` green\n- `ruff check` green\n- `ruff check src` green", ids={"unit", "lint"})
        assert [acnames.registered(c, REG) for c in named] == ["unit", "lint", None]
