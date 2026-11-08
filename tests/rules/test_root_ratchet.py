"""ROOTLINT (tl-e5t0.30): what the root ratchet counts in one file (the change-against-origin/main run is in real/test_ratchets_change.py),
and the list of offenders it is judged against."""
import ast

from rules import root_ratchet

BODY = "\n".join(f"    x{i} = {i}" for i in range(root_ratchet.LONG_SLOC + 1))
SRC = f'''"""doc"""
# a comment


def long():
    """doc"""
{BODY}
    if x0:
        pass
    for _ in ():
        pass


def short(a):
    try:
        return a
    except ValueError:
        return 0
'''


def counts(rel: str) -> dict[str, int]:
    return root_ratchet.file_counts(rel, ast.parse(SRC))


def test_a_root_file_counts_its_branches_long_functions_and_code_lines():
    got = counts("src/taskloop/cli/x.py")
    assert got["branch"] == 3 and got["long_function"] == 1  # if, for, try; only `long` is over the limit
    # two defs, 26 assignments, if and for with their `pass`, the try header and its two returns; the docstrings, the comment and the
    # `except` header are not code lines
    assert got["sloc"] == 2 + (root_ratchet.LONG_SLOC + 1) + 4 + 3


def test_a_file_that_is_not_a_root_counts_nothing():
    assert counts("packages/land/src/tlland/x.py") == {}
    assert counts("tests/rules/test_x.py") == {}


def test_the_launch_wire_and_composition_files_are_roots_through_the_contract():
    assert root_ratchet.is_root("src/taskloop/app/launch/loop.py")
    assert root_ratchet.is_root("src/taskloop/app/wire/doctor.py")
    assert not root_ratchet.is_root("src/taskloop/app/doctor/install.py")
    assert root_ratchet.is_root("src/taskloop/app/run/entry.py")
    assert root_ratchet.is_root("src/taskloop/app/run/stages.py")


def test_the_offenders_are_listed_worst_first():
    rows = root_ratchet.offenders()
    assert rows and rows[0].startswith("src/taskloop/app/run/entry.py"), rows[:3]


def test_counter_freezes_contract_membership_and_includes_descendants():
    text = "[importlinter:contract:nobody-imports-a-root]\nforbidden_modules =\n    taskloop.app.old\n"
    counter = root_ratchet.counter_for(text)
    tree = ast.parse("x = 1\n")
    assert counter("src/taskloop/app/old.py", tree)["sloc"] == 1
    assert counter("src/taskloop/app/old/child.py", tree)["sloc"] == 1
    assert counter("src/taskloop/app/older.py", tree) == {}
    assert root_ratchet.counter_for(None)("src/taskloop/app/old.py", tree) == {}


def test_counter_without_contract_keeps_fixed_roots_and_ignores_non_python():
    counter = root_ratchet.counter_for(None)
    tree = ast.parse("x = 1\n")
    for rel in ("src/taskloop/cli/x.py", "src/taskloop/hook/x.py", "skills/task-loop/tl.py"):
        assert counter(rel, tree)["sloc"] == 1
    assert counter("src/taskloop/cli/x.txt", tree) == {}
