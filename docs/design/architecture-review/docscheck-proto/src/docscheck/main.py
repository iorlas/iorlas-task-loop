"""The run behind the command line: build the world, pick the scope, print findings, return the exit code."""

from pathlib import Path

from docscheck.changed import Scope, scope_of
from docscheck.generate import graph_text, index_text
from docscheck.code_read import repo_check_ids
from docscheck.run import Config, load_world, run_check


def execute(command: str, docs: Path, ontology: Path, repo: Path | None, changed: list[Path], *, full: bool, package: Path, keys: bool = False) -> int:
    config = Config(docs, ontology, repo)
    world = load_world(config)
    if command == "generate":
        print(index_text(world.docs))
        print("\n## graph")
        print(graph_text(world.links, world.entries))
        return 0
    owner = {name: entry.doc for name, entry in world.entries.items()}
    sources = repo_check_ids(repo) if repo else {}
    scope = Scope(True, frozenset(d.id for d in world.docs)) if full else scope_of(
        changed, world.docs, world.kinds, world.links, owner, docs, repo, [ontology, package], sources)
    report = run_check(config, world, scope)
    for finding in report.findings:
        print(finding.line(keys=keys))
    for finding, task in report.waived:
        print(f"waived ({task}): {finding.line(keys=keys)}")
    print(f"checked {report.checked}/{report.total} docs, {len(report.findings)} findings, {len(report.waived)} waived, "
          f"{report.unchecked}/{report.rules} rules have no check or probe")
    return 1 if report.findings else 0
