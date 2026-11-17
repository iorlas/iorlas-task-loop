"""Direct Pydantic dependencies belong at explicit edges; existing debt may only shrink."""

import ast
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EDGE_MODULES = frozenset({
    "src/taskloop/agents/settings.py",
    "src/taskloop/plan_content.py",
    "src/taskloop/answer_failures.py",
    "src/taskloop/dash_model.py",
    "src/taskloop/operation_evidence.py",  # validated operation artifact interchange
    "src/taskloop/land_timing.py",  # validated stored land times and retry causes
    "src/taskloop/workflow.py",  # the workflow file is configuration, validated at its edge
})
# Initial census at 5aba3eb7. Remove resolved sites; never add entries to pass.
# Keys are path | enclosing symbol | canonical import | occurrence (not line).
KNOWN_EXCEPTIONS: frozenset[str] = frozenset({
    "src/taskloop/admit_rows.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/admit_rows.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/admit_rows.py|<module>|pydantic.Field|1",
    "src/taskloop/admit_store.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/admit_store.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/agents/config.py|<module>|pydantic.Field|1",
    "src/taskloop/agents/config.py|<module>|pydantic.JsonValue|1",
    "src/taskloop/agents/config.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/agents/stop_models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/agents/stop_models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/agents/stop_models.py|<module>|pydantic.Field|1",
    "src/taskloop/agents/stop_models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/answer_repair_models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/answer_repair_models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/answer_repair_models.py|<module>|pydantic.Field|1",
    "src/taskloop/answer_repair_store.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/answer_repair_store.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/answer_repair_store.py|<module>|pydantic.Field|1",
    "src/taskloop/attempt_loads.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/attempt_loads.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/check_admit_store.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/check_admit_store.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/check_feed.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/check_feed.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/check_feed.py|<module>|pydantic.Field|1",
    "src/taskloop/check_repeat/feedback.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/check_repeat/feedback.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/check_repeat/feedback.py|<module>|pydantic.Field|1",
    "src/taskloop/check_repeat/feedback.py|<module>|pydantic.field_validator|1",
    "src/taskloop/check_repeat/feedback.py|<module>|pydantic.model_validator|1",
    "src/taskloop/check_repeat/repair.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/cli_step.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/clock_jumps.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/clock_jumps.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/command_conclusion.py|<module>|pydantic.TypeAdapter|1",
    "src/taskloop/dash_duration.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/dash_duration.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/dash_server.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/discussion.py|<module>|pydantic.AwareDatetime|1",
    "src/taskloop/discussion.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/discussion.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/discussion.py|<module>|pydantic.TypeAdapter|1",
    "src/taskloop/discussion.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/drain/drain.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/drain/models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/drain/models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/drain/models.py|<module>|pydantic.Field|1",
    "src/taskloop/duration_evidence.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/duration_evidence.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/duration_evidence.py|<module>|pydantic.Field|1",
    "src/taskloop/duration_evidence.py|<module>|pydantic.model_validator|1",
    "src/taskloop/duration_file.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/earlier_attempt.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/earlier_attempt.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/implement_step.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/input_context.py|<module>|pydantic.AliasPath|1",
    "src/taskloop/input_context.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/input_context.py|<module>|pydantic.Field|1",
    "src/taskloop/land_conflict/abort_models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/land_conflict/abort_models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/land_conflict/cleanup_models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/land_conflict/models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/land_conflict/models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/land_conflict/models.py|<module>|pydantic.Field|1",
    "src/taskloop/land_conflict/models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/land_conflict/release_models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/merge/models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/merge/models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/merge/models.py|<module>|pydantic.Field|1",
    "src/taskloop/merge/models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/plan_reuse.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/plan_reuse.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/plan_reuse.py|<module>|pydantic.Field|1",
    "src/taskloop/plan_reuse.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/plan_reuse.py|<module>|pydantic.field_validator|1",
    "src/taskloop/publish_store.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/publish_store.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/recovery/continuation_models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/recovery/continuation_models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/recovery/continuation_models.py|<module>|pydantic.Field|1",
    "src/taskloop/recovery/execution_models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/recovery/execution_models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/recovery/execution_models.py|<module>|pydantic.Field|1",
    "src/taskloop/recovery/execution_models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/recovery/models.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/recovery/models.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/recovery/models.py|<module>|pydantic.Field|1",
    "src/taskloop/recovery/models.py|<module>|pydantic.model_validator|1",
    "src/taskloop/setup_store.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/setup_store.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/setup_store.py|<module>|pydantic.Field|1",
    "src/taskloop/setup_store.py|<module>|pydantic.computed_field|1",
    "src/taskloop/setup_timing.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/setup_timing.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/setup_timing.py|<module>|pydantic.Field|1",
    "src/taskloop/shelf_digest/artifact.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/shelf_digest/artifact.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/shelf_digest/identities.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/shelf_digest/identities.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/shelf_digest/identities.py|<module>|pydantic.Field|1",
    "src/taskloop/shelf_digest/identities.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/shelf_digest/installed.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/shelf_digest/installed.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/shelf_digest/installed.py|<module>|pydantic.Field|1",
    "src/taskloop/shelf_digest/installed.py|<module>|pydantic.ValidationError|1",
    "src/taskloop/shelf_request.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/shelf_request.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/shelf_request.py|<module>|pydantic.Field|1",
    "src/taskloop/shelf_request.py|<module>|pydantic.field_validator|1",
    "src/taskloop/task_content.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/task_content.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/task_content.py|<module>|pydantic.Field|1",
    "src/taskloop/task_event.py|<module>|pydantic.model_validator|1",
    "src/taskloop/task_event_cause.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/task_event_cause.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/task_event_cause.py|<module>|pydantic.Field|1",
    "src/taskloop/task_event_cause.py|<module>|pydantic.model_validator|1",
    "src/taskloop/wip.py|<module>|pydantic.BaseModel|1",
    "src/taskloop/wip.py|<module>|pydantic.ConfigDict|1",
    "src/taskloop/wip.py|<module>|pydantic.TypeAdapter|1",
})


class PydanticImports(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.scope: list[str] = []
        self.counts: Counter[str] = Counter()
        self.sites: dict[str, str] = {}

    def record(self, name: str, line: int) -> None:
        symbol = ".".join(self.scope) or "<module>"
        identity = f"{self.path}|{symbol}|{name}"
        self.counts[identity] += 1
        self.sites[f"{identity}|{self.counts[identity]}"] = f"{self.path}:{line}: {name} in {symbol}"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] == "pydantic":
                self.record(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module and node.module.split(".")[0] == "pydantic":
            for alias in node.names:
                self.record(f"{node.module}.{alias.name}", node.lineno)

    def visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.visit_scope(node)


def pydantic_sites(sources: Mapping[str, str]) -> dict[str, str]:
    sites: dict[str, str] = {}
    for path, source in sorted(sources.items()):
        if path in EDGE_MODULES:
            continue
        scanner = PydanticImports(path)
        scanner.visit(ast.parse(source, filename=path))
        sites.update(scanner.sites)
    return sites


def assert_pydantic_census(sites: dict[str, str], exceptions: frozenset[str]) -> None:
    added, stale = sites.keys() - exceptions, exceptions - sites.keys()
    assert not added, "New Pydantic imports outside edges: " + str({key: sites[key] for key in sorted(added)})
    assert not stale, "Remove resolved Pydantic exceptions: " + str(sorted(stale))


def test_repository_pydantic_imports_stay_at_edges() -> None:
    sources = {path.relative_to(ROOT).as_posix(): path.read_text() for path in (ROOT / "src/taskloop").rglob("*.py")}
    assert_pydantic_census(pydantic_sites(sources), KNOWN_EXCEPTIONS)


@pytest.mark.parametrize("source", [
    "from pydantic import BaseModel as Model\nclass Input(Model):\n    value: str",
    "import pydantic as p\nclass Input(p.BaseModel):\n    value: str",
    "import os, pydantic.dataclasses as data",
    "from pydantic.dataclasses import dataclass as model",
    "from pydantic import ValidationError, TypeAdapter, field_validator",
    "from pydantic import *",
    "if TYPE_CHECKING:\n    from pydantic import BaseModel",
    "def decode():\n    from pydantic import TypeAdapter",
    "class Decoder:\n    import pydantic\n    async def decode(self):\n        from pydantic import TypeAdapter",
])
def test_outside_imports_fail_and_equivalent_edge_models_pass(source: str) -> None:
    sites = pydantic_sites({"src/taskloop/domain.py": source})
    with pytest.raises(AssertionError, match="New Pydantic imports outside edges"):
        assert_pydantic_census(sites, frozenset())
    for edge in EDGE_MODULES:
        assert_pydantic_census(pydantic_sites({edge: source}), frozenset())


@pytest.mark.parametrize("path", [
    "src/taskloop/models.py",
    "src/taskloop/domain/settings.py",
    "src/taskloop/domain_models.py",
    "src/taskloop/other/agents/settings.py",
])
def test_edge_permission_requires_an_exact_path(path: str) -> None:
    with pytest.raises(AssertionError, match="outside edges"):
        assert_pydantic_census(pydantic_sites({path: "from pydantic import BaseModel"}), frozenset())


def test_edge_model_consumers_and_unrelated_names_pass() -> None:
    source = """
from taskloop.dash_model import TaskCard
from .pydantic import LocalModel
from . import pydantic
import pydantic_extra_types
text = 'from pydantic import BaseModel'
# import pydantic
"""
    assert_pydantic_census(pydantic_sites({"src/taskloop/consumer.py": source}), frozenset())


@pytest.mark.parametrize("changed", [
    "from pydantic import BaseModel, Field",
    "from pydantic import BaseModel\nfrom pydantic import BaseModel as Other",
    "def decode():\n    from pydantic import BaseModel",
    "from pydantic.main import BaseModel",
    "",
])
def test_added_duplicated_moved_or_stale_imports_fail(changed: str) -> None:
    path = "src/taskloop/debt.py"
    exceptions = frozenset(pydantic_sites({path: "from pydantic import BaseModel"}))
    with pytest.raises(AssertionError):
        assert_pydantic_census(pydantic_sites({path: changed}), exceptions)


def test_moving_an_import_between_modules_or_symbols_fails() -> None:
    source = "class Decoder:\n    async def decode(self):\n        from pydantic import TypeAdapter"
    path = "src/taskloop/debt.py"
    exceptions = frozenset(pydantic_sites({path: source}))
    assert_pydantic_census(pydantic_sites({path: source}), exceptions)
    for sources in ({"src/taskloop/moved.py": source}, {path: source.replace("decode(self)", "read(self)")}):
        with pytest.raises(AssertionError, match="outside edges"):
            assert_pydantic_census(pydantic_sites(sources), exceptions)


def test_formatting_and_aliases_preserve_identity_but_removing_debt_requires_shrinkage() -> None:
    path = "src/taskloop/debt.py"
    source = "from pydantic import BaseModel, ConfigDict"
    exceptions = frozenset(pydantic_sites({path: source}))
    reformatted = "\n# comment\nfrom pydantic import (\n    ConfigDict as Config,\n    BaseModel as Model,\n)"
    assert_pydantic_census(pydantic_sites({path: reformatted}), exceptions)
    remaining = pydantic_sites({path: "from pydantic import BaseModel"})
    with pytest.raises(AssertionError, match="Remove resolved Pydantic exceptions"):
        assert_pydantic_census(remaining, exceptions)
    assert_pydantic_census(remaining, frozenset({f"{path}|<module>|pydantic.BaseModel|1"}))
