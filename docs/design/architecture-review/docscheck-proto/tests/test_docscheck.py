"""Behavior of the docs checker: each rule fails on a small wrong doc and passes on the right one."""

import sys
from pathlib import Path

import pytest
from support import ONTOLOGY, check, codes, make_docs, make_repo, write

from docscheck import cli
from docscheck.changed import scope_of
from docscheck.run import Config, load_world
from docscheck.waivers import waiver_map


def test_a_clean_set_has_no_findings(tmp_path: Path) -> None:
    report = check(make_docs(tmp_path), make_repo(tmp_path))
    assert report.findings == []
    assert (report.rules, report.unchecked) == (1, 1)


def test_a_dangling_link_names_the_nearest_id(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, area_extra="touches: [area/b]\n")
    write(docs, "system/area/bb.md", (docs / "system/area/a.md").read_text().replace("touches: [area/b]\n", ""))
    report = check(docs)
    assert [f.message for f in report.findings if f.code == "dangling-ref"] == ["area/b; nearest: area/bb"]


def test_a_link_to_the_wrong_kind_is_refused(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, area_extra="touches: [term/thing]\n")
    assert "schema" in codes(check(docs))


def test_a_wikilink_in_a_cell_must_resolve(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    text = (docs / "system/area/a.md").read_text().replace("keeps its value", "keeps [[term/missing]] value")
    (docs / "system/area/a.md").write_text(text)
    assert [f.field for f in check(docs).findings if f.code == "dangling-ref"] == ["rules[0].holds"]


def test_an_enum_value_outside_the_set_fails_the_schema(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    write(docs, "system/persona/p.md", "---\nnature: robot\ncan:\n  - {does: \"act\", through: area/a}\n---\n")
    found = [f for f in check(docs).findings if f.doc == "persona/p"]
    assert [f.code for f in found] == ["schema"] and "robot" in found[0].message


def test_a_hedge_word_is_refused_and_a_scope_keyword_too(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    text = (docs / "system/area/a.md").read_text().replace("keeps its value", "should keep its value")
    text = text.replace("every module", "every module except one")
    (docs / "system/area/a.md").write_text(text)
    assert [f.field for f in check(docs).findings if f.code == "hedge-word"] == ["rules[0].applies_to", "rules[0].holds"]


CASES = """case_tables:
  - {name: t, states: [a, b]}
cases:
  - {table: t, state: a, effect: "does x"}
"""


def test_a_case_table_must_cover_every_declared_state_once(tmp_path: Path) -> None:
    report = check(make_docs(tmp_path, area_extra=CASES))
    assert [f.code for f in report.findings] == ["case-missing"]
    dup = check(make_docs(tmp_path / "d", area_extra=CASES + '  - {table: t, state: a, effect: "again"}\n  - {table: t, state: b, effect: "y"}\n'))
    assert codes(dup) == {"case-duplicate"}


def test_a_case_in_an_undeclared_table_or_state_fails(tmp_path: Path) -> None:
    extra = 'case_tables:\n  - {name: t, states: [a]}\ncases:\n  - {table: t, state: a, effect: "x"}\n  - {table: t, state: z, effect: "y"}\n  - {table: u, state: a, effect: "w"}\n'
    assert codes(check(make_docs(tmp_path, area_extra=extra))) == {"case-unknown-state", "case-table-undeclared"}


def test_a_lifecycle_that_matches_its_code_passes(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, lifecycle="")
    assert check(docs, make_repo(tmp_path)).findings == []


def test_a_state_nobody_reaches_is_reported(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, life_states=", island", lifecycle="")
    found = codes(check(docs, make_repo(tmp_path, '"one", "two", "three", "island"')))
    assert {"unreachable", "no-exit", "transition-missing"} <= found


def test_declared_states_that_differ_from_the_code_enum_are_drift(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, lifecycle="")
    report = check(docs, make_repo(tmp_path, '"one", "two", "three", "four"'))
    assert [f.message for f in report.findings if f.code == "enum-drift"] == ["doc has ['one', 'three', 'two'], code has ['four', 'one', 'three', 'two']"]


def test_a_lifecycle_must_declare_process_death_and_restart(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, lifecycle="")
    text = (docs / "system/lifecycle/l.md").read_text().replace("events: [go, process-death, restart]", "events: [go]")
    (docs / "system/lifecycle/l.md").write_text(text)
    assert {"event-required", "event-undeclared"} <= codes(check(docs, make_repo(tmp_path)))


WORKFLOW = """---
goal: "Reach the end."
actors: [persona/p]
areas: [area/a]
steps:
  - {do: "move it", actor: area/a, causes: lifecycle/l, event: %s}
---
"""


def test_a_workflow_step_must_name_an_event_its_lifecycle_declares(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, lifecycle="")
    write(docs, "system/persona/p.md", "---\nnature: human\ncan:\n  - {does: \"act\", through: area/a}\n---\n")
    write(docs, "system/workflow/w.md", WORKFLOW % "teleport")
    found = [f for f in check(docs, make_repo(tmp_path)).findings if f.doc == "workflow/w"]
    assert [f.code for f in found] == ["event-undeclared"]
    write(docs, "system/workflow/w.md", WORKFLOW % "go")
    assert [f for f in check(docs, make_repo(tmp_path)).findings if f.doc == "workflow/w"] == []


def test_code_references_must_resolve_and_limits_must_match(tmp_path: Path) -> None:
    extra = ('limits:\n  - {name: wait, source: "src/mod.py::WAIT", value: 9}\n'
             'operations:\n  - {name: go, source: "src/mod.py::nothing"}\n')
    report = check(make_docs(tmp_path, area_extra=extra), make_repo(tmp_path))
    assert codes(report) == {"limit-differs", "symbol-unresolved"}


def test_a_check_must_be_a_real_test_and_a_probe_must_exist(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, rule_extra=", check: check/test_keeps_its_value, probe: nope")
    assert codes(check(docs, make_repo(tmp_path))) == {"probe-unknown"}
    docs = make_docs(tmp_path / "x", rule_extra=", check: check/test_gone")
    assert codes(check(docs, make_repo(tmp_path / "x"))) == {"dangling-ref"}


def test_an_owns_glob_that_matches_nothing_is_reported(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    text = (docs / "system/area/a.md").read_text().replace('"src/mod.py"', '"src/gone/*.py"')
    (docs / "system/area/a.md").write_text(text)
    assert codes(check(docs, make_repo(tmp_path))) == {"glob-empty"}


def test_a_waiver_hides_its_finding_and_a_stale_one_is_a_finding(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, area_extra='limits:\n  - {name: wait, source: "src/mod.py::WAIT", value: 9}\n')
    repo = make_repo(tmp_path)
    key = check(docs, repo).findings[0].key
    waiver = f'---\nwaivers:\n  - {{finding: "{key}", task: task/tl-1, why: "known"}}\n---\n'
    write(docs, "waivers.md", waiver)
    report = check(docs, repo)
    assert (report.findings, len(report.waived)) == ([], 1)
    write(docs, "waivers.md", waiver.replace(key, "area/a:limits[0]:limit-differs@000000"))
    assert codes(check(docs, repo)) == {"limit-differs", "waiver-stale"}


def test_a_marker_naming_a_missing_rule_is_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo, "tests/test_marked.py", 'import pytest\n\n@pytest.mark.rule("a.9")\ndef test_marked() -> None:\n    assert True\n')
    assert codes(check(make_docs(tmp_path), repo)) == {"marker-dangling"}


def test_a_doc_outside_every_file_pattern_is_unplaced(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    write(docs, "notes/loose.md", "---\na: 1\n---\n")
    assert codes(check(docs)) == {"unplaced"}


def test_nothing_changed_is_a_skip_that_loads_no_heavy_module(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    docs = make_docs(tmp_path)
    for name in [m for m in sys.modules if m.startswith("docscheck.") and m not in {"docscheck.cli", "docscheck.gitport", "docscheck.values"}]:
        del sys.modules[name]
    code = cli.main(["check", "--docs", str(docs), "--ontology", str(ONTOLOGY), "--changed", str(tmp_path / "elsewhere.txt")])
    assert code == 0 and "skipped" in capsys.readouterr().out
    assert "docscheck.main" not in sys.modules and "docscheck.run" not in sys.modules


def test_a_change_to_a_doc_rechecks_it_and_the_docs_that_reference_it(tmp_path: Path) -> None:
    docs = make_docs(tmp_path, area_extra="touches: [area/b]\n")
    write(docs, "system/area/b.md", (docs / "system/area/a.md").read_text().replace("touches: [area/b]\n", ""))
    write(docs, "system/area/c.md", (docs / "system/area/b.md").read_text())
    world = load_world(Config(docs, ONTOLOGY))
    owner = {name: entry.doc for name, entry in world.entries.items()}
    changed = [docs / "system/area/b.md"]
    scope = scope_of(changed, world.docs, world.kinds, world.links, owner, docs, None, [ONTOLOGY], {})
    assert (scope.full, sorted(scope.doc_ids)) == (False, ["area/a", "area/b"])


def test_a_changed_repo_file_rechecks_the_docs_depending_on_it(tmp_path: Path) -> None:
    docs, repo = make_docs(tmp_path), make_repo(tmp_path)
    world = load_world(Config(docs, ONTOLOGY, repo))
    owner = {name: entry.doc for name, entry in world.entries.items()}
    scope = scope_of([repo / "src/mod.py"], world.docs, world.kinds, world.links, owner, docs, repo, [ONTOLOGY], {})
    assert sorted(scope.doc_ids) == ["area/a"]
    other = scope_of([repo / "src/other.py"], world.docs, world.kinds, world.links, owner, docs, repo, [ONTOLOGY], {})
    assert other.doc_ids == frozenset()


def test_a_change_to_the_ontology_rechecks_everything(tmp_path: Path) -> None:
    docs = make_docs(tmp_path)
    world = load_world(Config(docs, ONTOLOGY))
    scope = scope_of([ONTOLOGY / "area.yml"], world.docs, world.kinds, world.links, {}, docs, None, [ONTOLOGY], {})
    assert scope.full and len(scope.doc_ids) == len(world.docs)


def test_the_generated_index_and_graph_are_deterministic(tmp_path: Path) -> None:
    from docscheck.generate import graph_text, index_text

    docs = make_docs(tmp_path, area_extra="touches: [area/b]\n")
    write(docs, "system/area/b.md", (docs / "system/area/a.md").read_text().replace("touches: [area/b]\n", ""))
    world = load_world(Config(docs, ONTOLOGY))
    assert index_text(world.docs) == index_text(list(reversed(world.docs)))
    assert "area/a -> area/b" in graph_text(world.links, world.entries)
    assert waiver_map(world.docs, world.kinds) == {}
