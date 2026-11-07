"""Release's move is repeatable and refuses ambiguous bindings before writing."""

import pytest
from carve_release import plan, rewrite
from rules.arch_rules import production_graph

OLD = "taskloop" + ".app.release"


@pytest.mark.parametrize("source", [
    "from taskloop.app import release\n",
    "from taskloop.app import *\n",
    f"from {OLD} import *\n",
    f"from {OLD}.pins import *\n",
])
def test_release_carve_refuses_parent_and_star_bindings(source):
    assert rewrite(source)[1]


def test_release_carve_plans_renames_and_rewrites_then_accepts_the_moved_tree(tmp_path):
    old = tmp_path / "src/taskloop/app/release"
    old.mkdir(parents=True)
    (old / "__init__.py").write_text('"""Release."""\n')
    (old / "pins.py").write_text('"""Pins."""\n')
    consumer = tmp_path / "src/caller.py"
    consumer.write_text(f"from {OLD} import pins\n")
    moves, edits, errors = plan(tmp_path)
    assert errors == []
    assert len(moves) == 2
    assert edits == [(consumer, "from tlrelease import pins\n")]
    for source, dest in moves.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
    for path, text in edits:
        path.write_text(text)
    assert plan(tmp_path) == ({}, [], [])


def test_release_imports_only_kernel_gate_and_third_parties():
    graph = production_graph("tlrelease.")
    bad = [(source, target) for source, targets in graph.items() if source.startswith("tlrelease.")
           for target in targets if target.split(".")[0] not in {"tlrelease", "tlkernel", "tlgate"}]
    assert bad == []
