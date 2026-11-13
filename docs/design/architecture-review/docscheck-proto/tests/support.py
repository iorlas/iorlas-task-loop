"""Builders for small docs and a small target repo."""

from pathlib import Path

from docscheck.changed import Scope
from docscheck.run import Config, Report, load_world, run_check

ONTOLOGY = Path(__file__).resolve().parents[1] / "ontology"

TERMS = 'terms:\n  - {name: thing, definition: "A thing the tests name."}\n'
AREA = """---
read_when: tests
owns: ["src/mod.py"]
terms: [term/thing]
rules:
  - {id: 1, applies_to: "every module", holds: "keeps its value"%s}
%s---
"""
LIFECYCLE = """---
entity: term/thing
owner: area/a
source: "src/mod.py::Phase"
initial: one
terminal: [three]
states: [one, two, three%s]
events: [go, process-death, restart]
transitions:
  - {from: one, event: go, to: two}
  - {from: one, event: process-death, to: one}
  - {from: one, event: restart, to: one}
  - {from: two, event: go, to: three}
  - {from: two, event: process-death, to: two}
  - {from: two, event: restart, to: two}
%s---
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_repo(root: Path, phases: str = '"one", "two", "three"') -> Path:
    repo = root / "repo"
    write(repo, "src/mod.py", f"from typing import Literal\n\ntype Phase = Literal[{phases}]\nWAIT: int = 7\n")
    write(repo, "tests/test_mod.py", "def test_keeps_its_value() -> None:\n    assert True\n")
    return repo


def make_docs(root: Path, *, area_extra: str = "", rule_extra: str = "", lifecycle: str | None = None, life_extra: str = "",
              life_states: str = "") -> Path:
    docs = root / "docs"
    write(docs, "glossary.md", f"---\n{TERMS}---\n")
    write(docs, "system/area/a.md", AREA % (rule_extra, area_extra))
    if lifecycle is not None or life_states or life_extra:
        write(docs, "system/lifecycle/l.md", LIFECYCLE % (life_states, life_extra))
    return docs


def check(docs: Path, repo: Path | None = None, only: frozenset[str] | None = None) -> Report:
    world = load_world(Config(docs, ONTOLOGY, repo))
    scope = Scope(True, frozenset(d.id for d in world.docs)) if only is None else Scope(False, only)
    return run_check(Config(docs, ONTOLOGY, repo), world, scope)


def codes(report: Report) -> set[str]:
    return {finding.code for finding in report.findings}
