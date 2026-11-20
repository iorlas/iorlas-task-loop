"""Enum spelling belongs in step/claim codecs and stores; existing debt may only shrink.

This deliberately small static analysis never imports the application. Only a
receiver with a declared value field on a proven non-enum class is exempted.
Unresolved expressions fail closed, with the same exact census as known enums.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENUM_BASES = {"enum.Enum", "enum.IntEnum", "enum.StrEnum", "enum.Flag", "enum.IntFlag"}
CODECS = {"src/taskloop/step.py", "src/taskloop/claim.py", "src/taskloop/land_timing.py"}
# Initial census at da7309d0. Remove resolved sites; never add entries to pass.
# Keys are path | enclosing symbol | normalized receiver | occurrence (not line).
KNOWN_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "src/taskloop/agent_credentials.py|machine_credentials|harness|1",
        "src/taskloop/agent_credentials.py|machine_credentials|harness|2",
        "src/taskloop/agents/config.py|display|setting.harness|1",
        "src/taskloop/agents/config.py|display|setting.provider|1",
        "src/taskloop/answer_failures.py|AnswerFailureData.describe|self.rule|1",
        "src/taskloop/answer_read.py|read|answer|1",
        "src/taskloop/attempt.py|Attempts._validate|answer|1",
        "src/taskloop/check_repeat/feedback.py|stored_source|CheckRepeatReason.FAILED_CHECK|1",
        "src/taskloop/cli_drain.py|run|loaded.settings.db|1",
        "src/taskloop/cli_step.py|_next|settings.db|1",
        "src/taskloop/cli_step.py|_next|settings.artifacts|1",
        "src/taskloop/cli_step.py|_rounds|settings.artifacts|1",
        "src/taskloop/cli_step.py|_rounds|settings.db|1",
        "src/taskloop/cli_step.py|_rounds|settings.artifacts|2",
        "src/taskloop/cli_step.py|run|loaded.settings.db|1",
        "src/taskloop/cli_step.py|run|loaded.settings.artifacts|1",
        "src/taskloop/command_conclusion.py|encode|value|1",
        "src/taskloop/dash_board.py|card_of|found.status|1",
        "src/taskloop/dash_board.py|queued_card|found.status|1",
        "src/taskloop/dash_task.py|_checks_feed|each.state|1",
        "src/taskloop/dash_task.py|<module>|CodexSandbox.DANGER_FULL_ACCESS|1",
        "src/taskloop/drain/render.py|human|owner.role|1",
        "src/taskloop/factory_schema.py|<module>|each|1",
        "src/taskloop/factory_schema.py|<module>|each|2",
        "src/taskloop/factory_schema.py|<module>|each|3",
        "src/taskloop/factory_schema.py|<module>|ActionKind.CLAIM|1",
        "src/taskloop/factory_schema.py|<module>|ActionState.DONE|1",
        "src/taskloop/factory_schema.py|<module>|CheckRepeatReason.FAILED_CHECK|1",
        "src/taskloop/factory_schema.py|<module>|CheckRepeatReason.FAILED_CHECK|2",
        "src/taskloop/land_conflict/handoff.py|refused|outcome|1",
        "src/taskloop/land_conflict/handoff.py|stopped|result.reason|1",
        "src/taskloop/land_conflict/models.py|AdmissionRefused.__init__|outcome|1",
        "src/taskloop/plan_step.py|<module>|depth|1",
        "src/taskloop/profile.py|_land|each|1",
        "src/taskloop/recovery/observe.py|NativeProcesses.entry|state|1",
        "src/taskloop/recovery/observe.py|NativeProcesses.process|state|1",
        "src/taskloop/result_data.py|_show_data|task_status(each).status|1",
        "src/taskloop/result_data.py|_setup_data|each|1",
        "src/taskloop/result_data.py|_setup_data|each|2",
        "src/taskloop/result_data.py|_setup_data|each|3",
        "src/taskloop/shelf_digest/declarations.py|_target_names|target|1",
        "src/taskloop/shelf_digest/declarations.py|expression_name|node|1",
        "src/taskloop/shelf_digest/documentation.py|_docstring|first|1",
        "src/taskloop/shelf_digest/documentation.py|_docstring|first.value|1",
        "src/taskloop/shelf_digest/documentation.py|_docstring|first|2",
        "src/taskloop/shelf_digest/documentation.py|_docstring|first.value|2",
        "src/taskloop/shelf_digest/documentation.py|_docstring|first|3",
        "src/taskloop/shelf_digest/documentation.py|documentation_order|item.kind|1",
        "src/taskloop/shelf_digest/exports.py|_strings|item|1",
        "src/taskloop/shelf_digest/exports.py|_strings|item|2",
        "src/taskloop/shelf_digest/exports.py|_strings|item|3",
        "src/taskloop/shelf_digest/exports.py|PackageExports._statement|node|1",
        "src/taskloop/shelf_digest/exports.py|PackageExports._declare|node|1",
        "src/taskloop/shelf_digest/exports.py|PackageExports._declare|node|2",
        "src/taskloop/shelf_digest/exports.py|PackageExports._save_declaration|node|1",
        "src/taskloop/shelf_digest/facts.py|_fragment|node|1",
        "src/taskloop/shelf_digest/facts.py|_parameter_matches|expected|1",
        "src/taskloop/shelf_digest/facts.py|_parameter_matches|expected|2",
        "src/taskloop/slot_park.py|_saved|refused.reason|1",
        "src/taskloop/slot_park.py|_saved|parked.reason|1",
        "src/taskloop/step_render.py|_setup_lines|each|1",
        "src/taskloop/step_render.py|_setup_lines|each|2",
        "src/taskloop/task_event.py|TaskEvent.consistent|self.step|1",
        "src/taskloop/task_event.py|TaskEvent.consistent|self.agent_step|1",
        "src/taskloop/task_event_codec.py|reason|cause.reason|1",
        "src/taskloop/task_event_codec.py|reason|cause.reason|2",
        "src/taskloop/task_event_codec.py|reason|cause.reason|3",
        "src/taskloop/task_event_codec.py|reason|cause.reason|4",
        "src/taskloop/task_event_codec.py|reason|cause.reason|5",
        "src/taskloop/task_event_codec.py|reason|cause.leftovers.reason|1",
        "src/taskloop/task_event_codec.py|reason|cause.reason|6",
        "src/taskloop/task_event_codec.py|reason|cause.reason|7",
        "src/taskloop/task_event_codec.py|reason|cause.reason|8",
        "src/taskloop/task_event_codec.py|_checks|cause.reason|1",
        "src/taskloop/task_event_codec.py|_checks|cause.check.conclusion|1",
        "src/taskloop/task_event_codec.py|_checks|cause.setup|1",
        "src/taskloop/task_event_codec.py|_checks|cause.profile|1",
    }
)


def reference(node: ast.expr, module: str, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, f"{module}.{node.id}")
    if isinstance(node, ast.Attribute):
        return f"{reference(node.value, module, aliases)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return reference(node.value, module, aliases)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return reference(ast.parse(node.value, mode="eval").body, module, aliases)
    return ""


def imports(tree: ast.Module, module: str, package: bool) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                parts = module.split(".") if package else module.split(".")[:-1]
                prefix = ".".join(parts[: len(parts) - node.level + 1] + ([prefix] if prefix else []))
            aliases.update({alias.asname or alias.name: f"{prefix}.{alias.name}" for alias in node.names})
    return aliases


class Index:
    def __init__(self, sources: dict[str, str]) -> None:
        self.modules: dict[str, tuple[str, ast.Module, dict[str, str]]] = {}
        self.fields: dict[str, dict[str, str]] = {}
        self.bases: dict[str, set[str]] = {}
        self.returns: dict[str, str] = {}
        for path, source in sorted(sources.items()):
            parts = Path(path).with_suffix("").parts[1:]
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            tree = ast.parse(source, filename=path)
            aliases = imports(tree, module, parts[-1] == "__init__")
            self.modules[path] = module, tree, aliases
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    name = f"{module}.{node.name}"
                    self.bases[name] = {reference(base, module, aliases) for base in node.bases}
                    self.fields[name] = {
                        field.target.id: reference(field.annotation, module, aliases)
                        for field in node.body
                        if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)
                    }
                    self.index_returns(node.body, name, module, aliases)
            self.index_returns(tree.body, module, module, aliases)
        self.enums = self.descendants(ENUM_BASES)
        self.non_enums: set[str] = set()
        while pending := {name for name, bases in self.bases.items() if bases <= self.non_enums} - self.non_enums:
            self.non_enums.update(pending)

    def index_returns(self, body: list[ast.stmt], prefix: str, module: str, aliases: dict[str, str]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
                self.returns[f"{prefix}.{node.name}"] = reference(node.returns, module, aliases)

    def descendants(self, roots: set[str]) -> set[str]:
        found = roots.copy()
        while pending := {name for name, bases in self.bases.items() if bases & found} - found:
            found.update(pending)
        return found


type Binding = str | ast.expr | None


class Bindings(ast.NodeVisitor):
    """Collect one lexical scope, conservatively forgetting multiply written names."""

    def __init__(self, module: str, aliases: dict[str, str]) -> None:
        self.module, self.aliases = module, aliases
        self.values: dict[str, Binding] = {}

    def bind(self, name: str, value: Binding) -> None:
        self.values[name] = None if name in self.values else value

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id, None)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.bind(target.id, node.value)
            else:
                self.visit(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.bind(node.target.id, reference(node.annotation, self.module, self.aliases))
        if node.value:
            self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.bind(node.name, None)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bind(node.name, None)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bind(alias.asname or alias.name.split(".")[0], None)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.bind(alias.asname or alias.name, None)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bind(node.name, None)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name:
            self.bind(node.name, None)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.bind(node.rest, None)
        self.generic_visit(node)


class Scanner(ast.NodeVisitor):
    def __init__(self, index: Index, path: str) -> None:
        self.index, self.path = index, path
        self.module, self.tree, self.aliases = index.modules[path]
        module_bindings = Bindings(self.module, self.aliases)
        for statement in self.tree.body:
            if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                module_bindings.bind(statement.name, f"{self.module}.{statement.name}")
            elif not isinstance(statement, (ast.Import, ast.ImportFrom)):
                module_bindings.visit(statement)
        self.bindings = module_bindings.values
        self.symbols: list[str] = []
        self.class_scopes: dict[str, dict[str, Binding]] = {}
        self.occurrences: Counter[str] = Counter()
        self.sites: dict[str, str] = {}

    def resolve(self, node: ast.expr, seen: frozenset[str] = frozenset()) -> str:
        result = ""
        if isinstance(node, ast.Name):
            binding = self.bindings.get(node.id, reference(node, self.module, self.aliases))
            if node.id not in seen:
                result = binding if isinstance(binding, str) else self.resolve(binding, seen | {node.id}) if binding else ""
        elif isinstance(node, ast.Attribute):
            owner = self.resolve(node.value, seen)
            result = self.index.fields.get(owner, {}).get(node.attr, owner if owner in self.index.enums else f"{owner}.{node.attr}")
        elif isinstance(node, ast.Call):
            callee = self.resolve(node.func, seen)
            result = callee if callee in self.index.fields else self.index.returns.get(callee, "")
        return result

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "value":
            receiver = self.resolve(node.value)
            ordinary = receiver in self.index.non_enums and "value" in self.index.fields[receiver]
            if not ordinary:
                key = f"{self.path}|{'.'.join(self.symbols) or '<module>'}|{ast.unparse(node.value)}"
                self.occurrences[key] += 1
                kind = "enum" if receiver in self.index.enums else "unresolved"
                self.sites[f"{key}|{self.occurrences[key]}"] = f"{self.path}:{node.lineno} ({kind})"
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in [*node.decorator_list, *node.bases, *[keyword.value for keyword in node.keywords]]:
            self.visit(expression)
        previous = self.bindings
        self.symbols.append(node.name)
        self.class_scopes[".".join(self.symbols)] = previous
        local = Bindings(self.module, self.aliases)
        for statement in node.body:
            local.visit(statement)
        self.bindings = {**previous, **local.values}
        for parameter in node.type_params:
            self.visit(parameter)
        for statement in node.body:
            self.visit(statement)
        self.symbols.pop()
        self.bindings = previous

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        owner = ".".join(self.symbols)
        self.symbols.append(node.name)
        for expression in [*node.decorator_list, *node.args.defaults, *[each for each in node.args.kw_defaults if each]]:
            self.visit(expression)
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]:
            if argument and argument.annotation:
                self.visit(argument.annotation)
        if node.returns:
            self.visit(node.returns)
        for parameter in node.type_params:
            self.visit(parameter)
        previous = self.bindings
        local = Bindings(self.module, self.aliases)
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]:
            if argument:
                annotation = reference(argument.annotation, self.module, self.aliases) if argument.annotation else None
                if argument.arg == "self" and owner:
                    annotation = f"{self.module}.{owner}"
                local.bind(argument.arg, annotation)
        for statement in node.body:
            local.visit(statement)
        self.bindings = {**self.class_scopes.get(owner, previous), **local.values}
        for statement in node.body:
            self.visit(statement)
        self.symbols.pop()
        self.bindings = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in [*node.args.defaults, *[each for each in node.args.kw_defaults if each]]:
            self.visit(default)
        previous = self.bindings
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]
        self.bindings = {**previous, **{arg.arg: None for arg in arguments if arg}}
        self.visit(node.body)
        self.bindings = previous

    def visit_ListComp(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        previous = self.bindings
        self.bindings = previous.copy()
        for generator in node.generators:
            self.visit(generator.iter)
            for target in ast.walk(generator.target):
                if isinstance(target, ast.Name):
                    self.bindings[target.id] = None
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            if node.value is not None:
                self.visit(node.value)
        else:
            self.visit(node.elt)
        self.bindings = previous

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def scan(sources: dict[str, str]) -> dict[str, str]:
    index = Index(sources)
    sites: dict[str, str] = {}
    for path in index.modules:
        if path in CODECS or Path(path).name == "store.py" or Path(path).name.endswith("_store.py"):
            continue
        scanner = Scanner(index, path)
        scanner.visit(scanner.tree)
        sites.update(scanner.sites)
    return sites


def assert_census(sites: dict[str, str], exceptions: frozenset[str]) -> None:
    added, stale = sites.keys() - exceptions, exceptions - sites.keys()
    assert not added, "New enum/unresolved .value accesses outside codecs: " + str({key: sites[key] for key in sorted(added)})
    assert not stale, "Remove resolved .value exceptions: " + str(sorted(stale))


def test_repository_enum_values_stay_in_codecs() -> None:
    sources = {path.relative_to(ROOT).as_posix(): path.read_text() for path in (ROOT / "src/taskloop").rglob("*.py")}
    assert_census(scan(sources), KNOWN_EXCEPTIONS)


VOCABULARY = """from enum import StrEnum as Vocabulary
class Word(Vocabulary):
    YES = 'yes'
"""
FIELDS = """class Setting[T]:
    value: T
class Settings:
    chosen: Setting[str]
def settings() -> Settings:
    return Settings()
"""


def project_scan(root: Path, files: dict[str, str]) -> dict[str, str]:
    for name, source in files.items():
        path = root / "src/taskloop" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return scan({path.relative_to(root).as_posix(): path.read_text() for path in (root / "src/taskloop").rglob("*.py")})


@pytest.mark.parametrize(
    "consumer",
    [
        "text = Word.YES.value",
        "def render(word: Word):\n    return word.value",
        "def render():\n    word = Word.YES\n    return word.value",
        "class Words:\n    word: Word\n    def render(self):\n        return self.word.value",
        "async def render(word: 'Word'):\n    return word.value",
        "def render(word=Word.YES.value):\n    pass",
        "def render(word: Literal[Word.YES.value]):\n    pass",
        "class Child(Word):\n    pass\ntext = Child.YES.value",
    ],
)
def test_enum_access_outside_codecs_fails(tmp_path: Path, consumer: str) -> None:
    sites = project_scan(tmp_path, {"words.py": VOCABULARY + consumer})
    assert sites and all("(enum)" in diagnostic for diagnostic in sites.values())
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(sites, frozenset())


@pytest.mark.parametrize("path", ["step.py", "claim.py", "store.py", "custom_store.py", "feature/store.py", "feature/item_store.py"])
def test_codec_and_store_access_passes(tmp_path: Path, path: str) -> None:
    assert_census(project_scan(tmp_path, {path: VOCABULARY + "text = Word.YES.value"}), frozenset())


@pytest.mark.parametrize("path", ["codec.py", "task_event_codec.py", "feature/step.py", "stores.py", "store_extra.py", "__init__.py"])
def test_other_modules_are_not_implicitly_codecs(tmp_path: Path, path: str) -> None:
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(project_scan(tmp_path, {path: VOCABULARY + "text = Word.YES.value"}), frozenset())


def test_imported_annotations_fields_returns_and_assignments_distinguish_non_enums(tmp_path: Path) -> None:
    sites = project_scan(
        tmp_path,
        {
            "fields.py": FIELDS,
            "feature/use.py": """from ..fields import Setting as Field, Settings, settings as load
import taskloop.fields as fields
def render(config: 'Settings', field: Field[str]):
    alias = config.chosen
    created = fields.Setting()
    return field.value, alias.value, created.value, load().chosen.value
""",
        },
    )
    assert_census(sites, frozenset())


def test_class_fields_do_not_mask_a_global_enum_in_method_bodies(tmp_path: Path) -> None:
    sites = project_scan(
        tmp_path,
        {
            "words.py": VOCABULARY
            + FIELDS
            + """
field = Word.YES
class Consumer:
    field: Setting[str]
    def render(self):
        return field.value
"""
        },
    )
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(sites, frozenset())


@pytest.mark.parametrize(
    "consumer",
    [
        "def render(unknown):\n    return unknown.value",
        "def render(field: Setting[str]):\n    field = fetch()\n    return field.value",
        "def render(field: Setting[str]):\n    return (lambda field: field.value)(fetch())",
        "def render(field: Setting[str]):\n    return [field.value for field in fetch()]",
        "from taskloop.fields import Setting as field\ntext = [field.value for field in fetch()]",
        "def render(field: Setting[str]):\n    from vendor import field\n    return field.value",
        "def render(field: Setting[str]):\n    try:\n        work()\n    except Exception as field:\n        return field.value",
        "def render(field: Setting[str]):\n    match fetch():\n        case field:\n            return field.value",
        "class Consumer:\n    field = fetch()\n    text = field.value",
    ],
)
def test_unknown_or_shadowed_receivers_require_exact_exceptions(tmp_path: Path, consumer: str) -> None:
    sites = project_scan(tmp_path, {"fields.py": FIELDS + consumer})
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(sites, frozenset())
    assert_census(sites, frozenset(sites))


@pytest.mark.parametrize(
    "changed",
    [
        "def render(word: Word):\n    return word.value, word.value",
        "def moved(word: Word):\n    return word.value",
        "def render(other: Word):\n    return other.value",
        "def render(word: Word):\n    return word",
    ],
)
def test_added_duplicated_moved_or_removed_sites_fail_the_census(tmp_path: Path, changed: str) -> None:
    original = "def render(word: Word):\n    return word.value"
    exceptions = frozenset(project_scan(tmp_path, {"words.py": VOCABULARY + original}))
    with pytest.raises(AssertionError):
        assert_census(project_scan(tmp_path, {"words.py": VOCABULARY + changed}), exceptions)


def test_census_ignores_line_numbers_and_parentheses_but_requires_shrinkage(tmp_path: Path) -> None:
    original = "def render(word: Word):\n    return word.value"
    exceptions = frozenset(project_scan(tmp_path, {"words.py": VOCABULARY + original}))
    reformatted = "\n\ndef render(word: Word):\n    return (word).value"
    assert_census(project_scan(tmp_path, {"words.py": VOCABULARY + reformatted}), exceptions)
    removed = project_scan(tmp_path, {"words.py": VOCABULARY})
    with pytest.raises(AssertionError, match="Remove resolved"):
        assert_census(removed, exceptions)
    assert_census(removed, frozenset())


def test_moving_a_default_to_another_function_changes_the_site(tmp_path: Path) -> None:
    original = VOCABULARY + "def first(word=Word.YES.value):\n    pass"
    exceptions = frozenset(project_scan(tmp_path, {"words.py": original}))
    moved = VOCABULARY + "def second(word=Word.YES.value):\n    pass"
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(project_scan(tmp_path, {"words.py": moved}), exceptions)


def test_moving_access_to_another_module_changes_the_site(tmp_path: Path) -> None:
    sources = {"words.py": VOCABULARY + "text = Word.YES.value"}
    sites = scan({f"src/taskloop/{name}": text for name, text in sources.items()})
    moved = project_scan(tmp_path, {"moved.py": sources["words.py"]})
    with pytest.raises(AssertionError, match="outside codecs"):
        assert_census(moved, frozenset(sites))
