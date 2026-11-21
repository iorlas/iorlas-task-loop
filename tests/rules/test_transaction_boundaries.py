"""Recognizable external ports cannot execute in a lexical write scope.

This is a structural check, not a Python call graph. Imports, retained methods,
typed receivers and straightforward assignments are resolved; runtime fake-port
guards cover effects hidden behind application callbacks or dynamic dispatch.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src/taskloop"
GIT_METHODS = frozenset(
    {
        "identity",
        "refs",
        "tree",
        "blob",
        "merge_base",
        "is_ancestor",
        "worktrees",
        "worktree_state",
        "worktree",
        "dirty",
        "diff",
        "head",
        "branch",
        "remote_url",
        "stage",
        "stage_tracked",
        "record",
        "take_branch",
        "park",
        "push",
        "fetch",
        "sync",
        "delete_remote_at",
        "push_refspecs",
        "push_request",
        "push_lease",
        "delete_branch",
        "clean",
        "clean_ignored",
        "record_empty",
        "reset",
        "squash",
        "start_merge",
        "finish_merge",
        "abort_merge",
        "commit_tree",
        "update_ref",
    }
)
TRACKER_METHODS = frozenset({"ready", "show", "inspect", "claim", "unclaim", "close", "comment", "labels", "titles", "discussion"})
GIT_RECEIVERS = frozenset({"git", "repo", "repository", "worktree", "checkout", "checkouts", "views", "Repo", "Worktree", "Checkouts"})
TRACKER_RECEIVERS = frozenset({"tracker", "tasks", "Tracker", "Tasks", "TaskReadClient", "TaskWriteClient"})
CALLABLE_PORTS = frozenset(
    {
        "checkouts",
        "tasks",
        "claim",
        "unclaim",
        "discussion",
        "start",
        "spawn",
        "popen_registered",
        "run_registered",
        "inspect_task",
        "collect_discussion",
        "Checkouts",
        "Tasks",
        "Claim",
        "Unclaim",
        "Start",
        "CollectDiscussion",
    }
)
EXTERNAL_TYPES = GIT_RECEIVERS | TRACKER_RECEIVERS | CALLABLE_PORTS


@dataclass(frozen=True)
class Violation:
    path: Path
    function: str
    line: int
    call: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.function}: external call {self.call} in a write transaction"


class Boundaries(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.aliases: dict[str, str] = {}
        self.functions: list[str] = []
        self.depth = 0
        self.violations: list[Violation] = []

    def reference(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            name = f"{self.reference(node.value)}.{node.attr}"
            return self.aliases.get(name, name)
        if isinstance(node, ast.Call):
            return self.reference(node.func)
        if isinstance(node, ast.Subscript):
            return self.reference(node.value)
        return ""

    def bind(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            for left, right in zip(target.elts, value.elts, strict=True):
                self.bind(left, right)
        elif isinstance(target, (ast.Name, ast.Attribute)):
            name = ast.unparse(target)
            reference = self.reference(value)
            if reference:
                self.aliases[name] = reference
            else:
                self.aliases.pop(name, None)

    def parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.annotation is not None:
                annotation = self.reference(arg.annotation)
                if annotation.split(".")[-1] in EXTERNAL_TYPES:
                    self.aliases[arg.arg] = annotation

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.bind(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self.bind(node.target, node.value)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous = self.aliases.copy()
        # Constructor-injected fields are also visible in the other methods.
        for method in node.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                self.parameters(method)
                for statement in ast.walk(method):
                    if isinstance(statement, ast.Assign):
                        for target in statement.targets:
                            self.bind(target, statement.value)
        self.aliases = previous | {key: value for key, value in self.aliases.items() if key.startswith("self.")}
        self.functions.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.functions.pop()
        self.aliases = previous

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for expression in (*node.decorator_list, *node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)):
            self.visit(expression)
        previous, depth = self.aliases.copy(), self.depth
        self.depth = 0  # Defining a function does not execute its body in the enclosing transaction.
        self.functions.append(node.name)
        self.parameters(node)
        for statement in node.body:
            self.visit(statement)
        self.functions.pop()
        self.aliases, self.depth = previous, depth

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)):
            self.visit(expression)
        depth = self.depth
        self.depth = 0
        self.visit(node.body)
        self.depth = depth

    def writes(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False
        name = self.reference(node.func).split(".")[-1]
        return name in {"begin", "begin_immediate", "transaction"} or (
            name == "_connection"
            and any(
                keyword.arg == "write" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            )
        )

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        depth = self.depth
        for item in node.items:
            # Earlier managers have already entered when later expressions execute.
            self.visit(item.context_expr)
            if self.writes(item.context_expr):
                self.depth += 1
        for statement in node.body:
            self.visit(statement)
        self.depth = depth

    visit_AsyncWith = visit_With

    def external(self, reference: str) -> bool:
        parts = reference.split(".")
        receiver, method = set(parts[:-1]), parts[-1]
        if method in CALLABLE_PORTS:
            # Store.start is database work; Start and injected process ports spawn.
            return (
                method != "start"
                or len(parts) == 1
                or parts[:-1] == ["self"]
                or bool(receiver & EXTERNAL_TYPES)
                or parts[-2] in {"ports", "process", "launcher"}
                or parts[0] == "stream_proc"
            )
        if receiver & GIT_RECEIVERS and method in GIT_METHODS:
            return True
        if receiver & TRACKER_RECEIVERS and method in TRACKER_METHODS:
            return True
        return parts[0] in {"git_porcelain", "beads_client"}

    def visit_Call(self, node: ast.Call) -> None:
        if self.depth and self.external(self.reference(node.func)):
            self.violations.append(Violation(self.path, ".".join(self.functions) or "<module>", node.lineno, ast.unparse(node.func)))
        self.generic_visit(node)


def violations(source: str, path: Path) -> list[Violation]:
    visitor = Boundaries(path)
    visitor.visit(ast.parse(dedent(source)))
    return visitor.violations


def test_no_external_port_executes_in_a_write_transaction() -> None:
    found = [violation for path in sorted(ROOT.rglob("*.py")) for violation in violations(path.read_text(), path.relative_to(ROOT))]
    assert not found, "\n".join(map(str, found))


@pytest.mark.parametrize(
    "boundary",
    [
        "begin(con)",
        "begin_immediate(con)",
        "store.begin(con)",
        "self.begin(con)",
        "self._connection(write=True)",
        "self.registering._connection(write=True)",
    ],
)
@pytest.mark.parametrize(
    "call",
    [
        "repo.refs([])",
        "repo.push('task')",
        "tracker.claim('task')",
        "self.checkouts(path)",
        "self.start(argv)",
    ],
)
def test_external_calls_are_rejected_in_each_write_scope(boundary: str, call: str) -> None:
    source = f"def record():\n    with {boundary}:\n        {call}\n"
    assert violations(source, Path("slice/store.py")) == [Violation(Path("slice/store.py"), "record", 3, call.split("(", 1)[0])]


@pytest.mark.parametrize(
    "source, call",
    [
        ("from sqlite_sidecar import transaction as tx\nwith tx(con):\n    repo.tree('HEAD')", "repo.tree"),
        ("import sqlite_sidecar as db\nwith db.transaction(con):\n    tracker.show('task')", "tracker.show"),
        ("tx = self.begin\nread = repo.refs\nwith tx(con):\n    read([])", "read"),
        ("git = repo\nread = git.tree\nagain = read\nwith begin(con):\n    again('HEAD')", "again"),
        ("from stream_proc import popen_registered as launch\nwith begin(con):\n    launch(argv)", "launch"),
        ("from git_porcelain import Repo as Git\ndef save(r: Git):\n    with begin(con):\n        r.record('message')", "r.record"),
        ("from taskloop.launch import Start\ndef save(launch: Start):\n    with begin(con):\n        launch(argv)", "launch"),
        ("def save(claim: Claim):\n    with begin(con):\n        claim('task')", "claim"),
        ("with begin(con), repo.worktree(path):\n    pass", "repo.worktree"),
        ("with reading(), begin(con), ports.claim('task'):\n    pass", "ports.claim"),
        ("with begin(con):\n    ports.start(argv)", "ports.start"),
        ("start = ports.start\nwith begin(con):\n    start(argv)", "start"),
        ("claim, read = tracker.claim, repo.refs\nwith begin(con):\n    read([])", "read"),
        ("with begin(con):\n    with reading():\n        repo.diff()", "repo.diff"),
        ("with begin(con):\n    def later(value=repo.tree('HEAD')):\n        pass", "repo.tree"),
        ("with begin(con):\n    later = lambda value=tracker.show('task'): None", "tracker.show"),
        (
            "class Writer:\n    def __init__(self, source: Repo):\n        self.retained = source\n"
            "    def save(self):\n        with self.begin(con):\n            self.retained.fetch('origin')",
            "self.retained.fetch",
        ),
        (
            "class Writer:\n    def __init__(self, launch: Start):\n        self.go = launch\n"
            "    def save(self):\n        with self.begin(con):\n            self.go(argv)",
            "self.go",
        ),
    ],
)
def test_imports_receivers_and_retained_port_aliases_are_checked(source: str, call: str) -> None:
    found = violations(source, Path("nested/store.py"))
    assert len(found) == 1 and found[0].call == call
    assert str(found[0]).startswith(f"nested/store.py:{found[0].line}:")
    assert "external call" in str(found[0])


@pytest.mark.parametrize(
    "source",
    [
        "with begin(con):\n    con.execute('UPDATE slot SET value=1')\n    store.record(con, encode(value), clock())",
        "with self._connection(write=True) as con:\n    target.record_release(con, value, self.clock(), False)",
        "with self._connection():\n    repo.refs([])",
        "with self._connection(write=False):\n    tracker.show('task')",
        "repo.fetch('origin')\nwith begin(con):\n    con.execute(sql)\nrepo.push('task')",
        "with begin(con):\n    def later():\n        repo.push('task')\n    callback = lambda: tracker.claim('task')",
        "with begin(con):\n    pass\nwith reading():\n    self.start(argv)",
        "with begin(con):\n    def later():\n        pass\n    store.start(value)",
        "with begin(con):\n    ports.store.start(value)\n    row = decode(con.execute(sql).fetchone())",
        "with repo.worktree(path), begin(con):\n    con.execute(sql)",
    ],
)
def test_database_work_and_calls_outside_write_scopes_are_permitted(source: str) -> None:
    assert violations(source, Path("store.py")) == []
