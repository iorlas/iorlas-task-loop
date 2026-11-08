"""Pure examples of the layout lock's node, move and contract boundaries."""
import pytest

from rules import layout_lock as lock

A = "src/taskloop/app" + "/plan/a.py"
B = "src/taskloop/app" + "/plan/b.py"
C = "packages/land/src/tlland/c.py"
SECTION = "importlinter:contract:boundary"


@pytest.mark.parametrize(("path", "expected"), [
    (A, "app/plan"), ("src/taskloop/stores/db.py", "stores"),
    ("packages/dash/src/tldash/page.py", "packages/dash"), ("packages/delegate/src/delegate/main.py", "packages/delegate"),
    ("packages/kernel/src/tlkernel/ids.py", "packages/kernel"),
    ("src/taskloop/main.py", "taskloop:main.py"), ("src/taskloop/app/main.py", "app:main.py"),
    ("tests/main.py", None), ("dev/main.py", None), ("skills/main.py", None), ("src/taskloop/a.txt", None),
])
def test_node_of(path, expected):
    assert lock.node_of(path) == expected


def test_new_node():
    assert "node" in lock.classify_files([("A", "", C)], {A: "app/plan"})


def test_whole_node_deletion():
    assert lock.classify_files([("D", A, "")], {A: "app/plan"}) == {"node": ["removed node app/plan"]}


def test_cross_node_move():
    assert lock.classify_files([("R100", A, C)], {A: "app/plan", B: "app/plan", C: "packages/land"}) == {
        "move": [f"{A} -> {C}"]}


def test_new_top_level_module():
    assert "node" in lock.classify_files([("A", "", "src/taskloop/new.py")], {A: "app/plan"})


@pytest.mark.parametrize("entries", [
    [("A", "", "src/taskloop/app" + "/plan/new.py")], [("M", A, A)], [("D", A, "")], [("R100", A, B)],
])
def test_in_node_feature_is_free(entries):
    assert lock.classify_files(entries, {A: "app/plan", B: "app/plan"}) == {}


@pytest.mark.parametrize(("before", "after"), [
    ({SECTION: {}}, {}),
    ({SECTION: {"forbidden_modules": "a\nb"}}, {SECTION: {"forbidden_modules": "a"}}),
    ({SECTION: {}}, {SECTION: {"ignore_imports": "a -> b"}}),
    ({SECTION: {"allow_indirect_imports": "False"}}, {SECTION: {"allow_indirect_imports": "True"}}),
    ({SECTION: {}}, {SECTION: {"allow_indirect_imports": "true"}}),
])
def test_contract_loosening(before, after):
    assert lock.contract_loosening(before, after)


@pytest.mark.parametrize("option", ["source_modules", "forbidden_modules", "layers", "containers"])
def test_removed_multiline_constraint(option):
    assert lock.contract_loosening({SECTION: {option: "a\nb"}}, {SECTION: {option: "a"}})


@pytest.mark.parametrize(("before", "after"), [
    ({}, {SECTION: {"source_modules": "a", "allow_indirect_imports": "true"}}),
    ({SECTION: {"source_modules": "a"}}, {SECTION: {"source_modules": "a\nb"}}),
    ({SECTION: {"forbidden_modules": "a"}}, {SECTION: {"forbidden_modules": "a\nb"}}),
    ({SECTION: {"layers": "a"}}, {SECTION: {"layers": "a\nb"}}),
])
def test_strengthening_is_free(before, after):
    assert lock.contract_loosening(before, after) == []


def test_parse_contracts():
    assert lock.parse_contracts("[importlinter]\nroot_package = taskloop\n[" + SECTION +
                                "]\nforbidden_modules =\n    a\n    b\nname = 100% boundary\n") == {
        SECTION: {"forbidden_modules": "\na\nb", "name": "100% boundary"}}


@pytest.mark.parametrize("path", ["tests/rules/gate_rules.py", "tests/rules/ratchet_change.py",
                                 "tests/rules/real/test_ratchets_change.py"])
def test_protected_rule_edit(path):
    assert lock.rule_changes([path]) == [path]


@pytest.mark.parametrize(("before", "after", "bad"), [
    ("LIMITS_S = 1\nx = 1", "LIMITS_S = 2\nx = 1", True),
    ("LIMITS_S = 1\nx = 1", "LIMITS_S = 1\nx = 2", False),
])
def test_only_limits_line_is_protected(before, after, bad):
    assert bool(lock.rule_changes(["tests/conftest.py"], before, after)) == bad


@pytest.mark.parametrize("reason", ["one", "one two", "one two three"])
def test_short_allow_reason_does_not_count(reason):
    assert lock.allowed_kinds(f"Layout-allow: move {reason}") == set()


def test_allow_move_allows_only_moves():
    assert lock.allowed_kinds("subject\n\nLayout-allow: move this move needs four words\n") == {"move"}


@pytest.mark.parametrize("kind", ["node", "move", "contract"])
def test_valid_allow_kind(kind):
    assert lock.allowed_kinds(f"Layout-allow: {kind} a reason four words") == {kind}
