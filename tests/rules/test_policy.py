"""Retain static caps and disallow hidden baseline or process imports."""

import ast
import io
import re
import tokenize
import tomllib
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(path for folder in ("src", "tests") for path in (ROOT / folder).rglob("*.py"))


def code_lines(source: str, tree: ast.Module) -> set[int]:
    """Count nonblank, noncomment, nondocstring lines as in the baseline policy."""
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in ignored:
            lines.update(range(token.start[0], token.end[0] + 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.difference_update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_source_policy(path: Path) -> None:
    source = path.read_text()
    tree = ast.parse(source)
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    lines = code_lines(source, tree)
    cap = limits["test-file"] if path.is_relative_to(ROOT / "tests") else limits["code-file"]
    assert len(lines) <= cap, path
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            assert len(lines & set(range(start, (node.end_lineno or node.lineno) + 1))) <= limits["function"], node.name
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.Name):
            assert node.id not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.ImportFrom):
            assert all(alias.name not in {"Any", "cast"} for alias in node.names)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(name.split(".")[0] not in {"subprocess", "tlkernel", "tltestkit", "delegate"} for name in names)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert not any(marker in token.string for marker in ("type: ignore", "pyrefly: ignore", "noqa"))


def test_caps_cannot_be_relaxed() -> None:
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    assert limits == {"code-file": 400, "function": 80, "test-file": 800}



# Every SQL write in the source, by (verb, table) -> the one module allowed to issue it. Anything unlisted is refused.
WRITERS = {
    ("CREATE TABLE", "recovery_intent"): "factory_schema.py",
    ("CREATE INDEX", "recovery_intent"): "factory_schema.py",
    ("INSERT", "recovery_intent"): "recovery/state_store.py",
    ("UPDATE", "recovery_intent"): "recovery/state_store.py",
    ("CREATE TABLE", "agent_stop"): "factory_schema.py",
    ("INSERT", "agent_stop"): "agents/stop_store.py",
    ("UPDATE", "agent_stop"): "agents/stop_store.py",
    ("CREATE TABLE", "merge_operation"): "factory_schema.py",
    ("CREATE TABLE", "land_conflict"): "factory_schema.py",
    ("INSERT", "land_conflict"): "land_conflict/store.py",
    ("UPDATE", "land_conflict"): "land_conflict/store.py",
    ("INSERT", "merge_operation"): "merge/store.py",
    ("UPDATE", "merge_operation"): "merge/store.py",
    ("CREATE TABLE", "drain_state"): "factory_schema.py",
    ("CREATE TABLE", "drain_action"): "factory_schema.py",
    ("CREATE INDEX", "drain_action"): "factory_schema.py",
    ("INSERT", "drain_state"): "drain/store.py",
    ("UPDATE", "drain_state"): "drain/store.py",
    ("INSERT", "drain_action"): "drain/store.py",
    ("UPDATE", "drain_action"): "drain/store.py",
    ("CREATE TABLE", "slot"): "factory_schema.py",
    ("CREATE TABLE", "reservation"): "factory_schema.py",
    ("CREATE TABLE", "attempt"): "factory_schema.py",
    ("CREATE TABLE", "execution"): "factory_schema.py",
    ("CREATE TABLE", "verification"): "factory_schema.py",
    ("CREATE TABLE", "slot_release"): "factory_schema.py",
    ("CREATE TABLE", "published_branch"): "factory_schema.py",
    ("CREATE TABLE", "setup_run"): "factory_schema.py",
    ("CREATE TABLE", "checks_attempt"): "factory_schema.py",
    ("CREATE TABLE", "check_result"): "factory_schema.py",
    ("CREATE TABLE", "land_candidate"): "factory_schema.py",
    ("CREATE INDEX", "attempt"): "factory_schema.py",
    ("CREATE INDEX", "land_candidate"): "factory_schema.py",  # `land_delivered`: at most one delivered candidate per checks attempt
    ("CREATE TABLE", "task_hold"): "factory_schema.py",
    ("INSERT", "task_hold"): "hold_store.py",  # a hold's record, fenced on its attempt and cause being current
    ("UPDATE", "task_hold"): "hold_store.py",  # its tracker writes' phases and its clearing, each fenced on `rev`
    ("DELETE FROM", "task_hold"): "hold_store.py",  # a hold whose cause is gone before it finished (`retire`)
    ("INSERT", "land_candidate"): "land_store.py",  # the candidate's row, inside the reserving transaction (`land_store.insert`)
    ("UPDATE", "land_candidate"): "land_store.py",  # also the release's record (`land_store.record_release`)
    ("INSERT", "checks_attempt"): "check_store.py",  # the admission's row, inside its transaction (`check_store.insert`)
    ("UPDATE", "checks_attempt"): "check_store.py",  # also the release's record (`check_store.record_release`)
    ("INSERT", "check_result"): "check_store.py",
    ("UPDATE", "check_result"): "check_store.py",
    ("INSERT", "setup_run"): "setup_store.py",
    ("UPDATE", "setup_run"): "setup_store.py",
    ("INSERT", "slot"): "slots.py",
    ("INSERT", "reservation"): "admit_rows.py",
    ("INSERT", "attempt"): "admit_rows.py",
    ("UPDATE", "reservation"): "admit_chain.py",  # a repeat's takeover
    ("UPDATE", "slot"): "admit_rows.py",
    ("INSERT", "slot_release"): "slot_release.py",
    ("UPDATE", "slot_release"): "slot_release.py",
    ("DELETE FROM", "reservation"): "slot_release.py",
    ("INSERT", "published_branch"): "publish.py",
    ("INSERT", "execution"): "attempt_store.py",
    ("INSERT", "verification"): "attempt_store.py",
    ("UPDATE", "attempt"): "attempt_store.py",  # also the deadline renewal after a reboot, in the entry registration's write
    ("UPDATE", "execution"): "attempt_store.py",
}
# A statement verb and its table; an index (`CREATE [UNIQUE] INDEX <name> ON <table>`) is written as `CREATE INDEX` of
# the table after `ON`.
WRITE = re.compile(
    r"\b(?:(CREATE\s+TABLE|(?:INSERT|REPLACE)(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+(\w+)"
    r"|CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\w+\s+ON\s+(\w+))", re.IGNORECASE
)


def write_of(match: re.Match[str]) -> tuple[str, str]:
    """The (kind, table) one `WRITE` match names."""
    if match.group(3) is not None:
        return "CREATE INDEX", match.group(3).lower()
    verb = " ".join(match.group(1).upper().split())
    kind = "INSERT" if verb.startswith(("INSERT", "REPLACE")) else verb.split()[0] if verb.startswith("UPDATE") else verb
    return kind, match.group(2).lower()


def sql_writes() -> set[tuple[str, str, str]]:
    paths = (ROOT / "src" / "taskloop").rglob("*.py")
    return {(*write_of(match), str(path.relative_to(ROOT / "src" / "taskloop"))) for path in paths
            for match in WRITE.finditer(path.read_text())}


def test_every_sql_write_has_its_one_owner() -> None:
    found = sql_writes()
    assert {(kind, table): owner for kind, table, owner in found} == WRITERS
    assert len(found) == len(WRITERS), sorted(found)


@pytest.mark.parametrize(("statement", "write"), [
    ("INSERT INTO slot(a) VALUES (1)", ("INSERT", "slot")), ("REPLACE INTO reservation VALUES (1)", ("INSERT", "reservation")),
    ("delete from attempt", ("DELETE FROM", "attempt")), ("UPDATE OR ABORT slot SET a=1", ("UPDATE", "slot")),
    ("CREATE UNIQUE INDEX one ON land_candidate(a) WHERE b", ("CREATE INDEX", "land_candidate")),
    ("create index if not exists two\non  Attempt (a)", ("CREATE INDEX", "attempt")), ("CREATE TABLE slot (a)", ("CREATE TABLE", "slot")),
])
def test_write_pattern_catches_spelling_variants(statement: str, write: tuple[str, str]) -> None:
    match = WRITE.search(statement)
    assert match is not None and write_of(match) == write


# The remote and ref writes below (sync, the other pushes, branch and remote-ref deletion) have no owner: unused.
GIT_WRITES = frozenset({
    "stage", "stage_tracked", "record", "take_branch", "park", "push", "fetch", "sync", "delete_remote_at", "push_refspecs",
    "push_request", "push_lease", "delete_branch", "clean", "reset", "squash",
    "start_merge", "finish_merge", "abort_merge", "commit_tree", "update_ref",
})


DYNAMIC = frozenset({"getattr", "methodcaller", "attrgetter"})  # calls that reach an attribute by a string name


def git_names(tree: ast.AST) -> set[str]:
    """Every Git write (`GIT_WRITES`) one module uses: a call or reference of that attribute on any receiver, a bare call
    of that name, or the name as a string argument of `getattr`, `methodcaller` or `attrgetter`. Any other string (a
    refusal word such as `reset` in a word table) is not a use. Its limit: a name built at runtime (`getattr(slot, "re" +
    "cord")`) or a write through another library API is not seen."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        if not isinstance(node, ast.Call):
            continue
        called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
        found.update({called} if isinstance(node.func, ast.Name) and called is not None else set())
        if called in DYNAMIC:
            found.update(arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str))
    return found & GIT_WRITES


def git_writers() -> set[tuple[str, str]]:
    """Every use of a Git write in the factory source, by module (`git_names`)."""
    root = ROOT / "src" / "taskloop"
    return {(name, str(path.relative_to(root))) for path in root.rglob("*.py") for name in git_names(ast.parse(path.read_text()))}


@pytest.mark.parametrize(("source", "names"), [
    ("slot.reset(x)", {"reset"}), ("hook = slot.park", {"park"}), ("reset()", {"reset"}), ('getattr(slot, "record")()', {"record"}),
    ('operator.methodcaller("clean")', {"clean"}), ('attrgetter("push")', {"push"}),
    ('WORDS = ("reset", "clean")', set()), ('word = "environment:reset"', set()), ('f(reset)', set()),
], ids=["call", "reference", "bare_call", "getattr", "methodcaller", "attrgetter", "word_table", "refusal_word", "plain_name"])
def test_the_git_write_matcher_sees_uses_and_not_words(source: str, names: set[str]) -> None:
    assert git_names(ast.parse(source)) == names


def test_only_the_commit_prepare_release_publish_environment_and_land_modules_write_git() -> None:
    """`clean` is the environment reset's (the slot's ignored files and nested repositories, before each setup); `reset`
    too (a checks slot's tracked files back to exactly X, tl-8bh9.14.6 section 8). The checks block writes no Git. The
    land's squash (objects only) is `land_target`'s, its fetch of origin's `main` and its push of S `land_push`'s."""
    expected = {
        ("stage", "factory_commit.py"), ("record", "factory_commit.py"), ("take_branch", "prepare.py"), ("park", "prepare.py"),
        ("park", "slot_release.py"), ("park", "wip.py"), ("reset", "wip.py"),
        ("stage", "wip.py"), ("commit_tree", "wip.py"), ("update_ref", "wip.py"), ("abort_merge", "slot_release.py"),
        ("park", "merge/start.py"), ("start_merge", "merge/start.py"), ("finish_merge", "merge/start.py"),
        ("fetch", "merge/start.py"),
        ("stage", "merge/start.py"), ("stage", "merge/git.py"), ("update_ref", "merge/git.py"), ("take_branch", "merge/git.py"),
        ("stage", "land_conflict/preserve.py"), ("commit_tree", "land_conflict/preserve.py"),
        ("update_ref", "land_conflict/preserve.py"),
            ("abort_merge", "land_conflict/abort.py"),
            ("push", "publish.py"), ("clean", "environment.py"), ("reset", "environment.py"),
        ("squash", "land_target.py"), ("fetch", "land_push.py"), ("push", "land_push.py"),
    }
    assert git_writers() == expected


def bd_importers() -> set[str]:
    """Every factory module that imports the tracker client `Bd` (from `beads_client` or a submodule, or the module itself
    to reach `beads_client.Bd`)."""
    found: set[str] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "beads_client":
                found.update(path.name for alias in node.names if alias.name in {"Bd", "client", "*"})
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "beads_client" for alias in node.names):
                found.add(path.name)
    return found


def test_only_tracker_client_constructs_the_tracker_client() -> None:
    """The tracker's writes (claim, unclaim, heartbeat) have one wiring owner."""
    assert bd_importers() == {"tracker_client.py"}


SIGNAL_USES = frozenset({"signal", "SIGINT", "SIGTERM", "SIGHUP", "SIG_IGN", "SIG_DFL", "default_int_handler", "getsignal"})
# Sending or timing signals, under any receiver (`os.kill`, `signal.alarm`, `proc.kill`): no factory source or test uses one.
SIGNALLING = frozenset({
    "kill", "killpg", "alarm", "setitimer", "pthread_kill", "pthread_sigmask", "set_wakeup_fd", "pidfd_send_signal",
    "raise_signal", "siginterrupt", "sigwait", "sigtimedwait",
})


def signal_uses(path: Path) -> tuple[set[str], set[str], set[str]]:
    """In one file: how `signal` or `_signal` is imported (`import`, `alias`, `from`), every dynamic import
    (`import_module`, `__import__`), and every signalling name used as an attribute or a bare name."""
    imports: set[str] = set()
    dynamic: set[str] = set()
    signalling: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"signal", "_signal"}:
                    imports.add("import" if alias.name == "signal" and alias.asname is None else "alias")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"signal", "_signal"}:
            imports.add("from")
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if name in {"import_module", "__import__"}:
            dynamic.add(name)
        if name in SIGNALLING:
            signalling.add(name)
    return imports, dynamic, signalling


def test_the_one_signal_owner_installs_only_the_rounds_handlers_and_nothing_sends_a_signal() -> None:
    """AGENTS.md's one exception: only `interrupts.py` imports `signal`, plainly (no alias, no `from`, no `_signal`, no
    dynamic import anywhere), and uses only what installs and restores the SIGINT, SIGTERM, SIGHUP handlers; no factory source or test
    sends or times a signal (`SIGNALLING`), and tests never import `signal` (so never install a handler)."""
    owner = ROOT / "src" / "taskloop" / "interrupts.py"
    for path in FILES:
        imports, dynamic, signalling = signal_uses(path)
        assert imports == ({"import"} if path == owner else set()), path
        assert dynamic == signalling == set(), path
    tree = ast.parse(owner.read_text())
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "signal"}
    assert used == SIGNAL_USES
    assert not any(isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names) for node in ast.walk(tree))


# Replacing or forking this process, or another way to start one: none exists in the factory (the layer above owns versions).
REPLACING = frozenset({
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp", "fork",
    "forkpty", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "system", "popen",
    "create_subprocess_exec", "create_subprocess_shell", "ProcessPoolExecutor", "fork_exec",
})
PROCESS_MODULES = frozenset({"pty", "multiprocessing", "_posixsubprocess", "concurrent.futures.process"})
DYNAMIC_IMPORTS = frozenset({"import_module", "__import__"})


def _called(node: ast.Call) -> str | None:
    return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None


def _process_module(name: str) -> list[str]:
    return [module for module in PROCESS_MODULES if name == module or name.startswith(module + ".")]


def _strings_of(nodes: list[ast.expr]) -> list[str]:
    return [node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _by_string(node: ast.AST) -> list[str]:
    """A `REPLACING` name reached by a string: `getattr(os, "fork")`, `vars(os)["fork"]`, `os.__dict__["fork"]`."""
    if isinstance(node, ast.Call) and _called(node) == "getattr":
        return [name for name in _strings_of(node.args[1:2]) if name in REPLACING]
    if isinstance(node, ast.Subscript) and ((isinstance(node.value, ast.Call) and _called(node.value) == "vars")
                                            or (isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__")):
        return [name for name in _strings_of([node.slice]) if name in REPLACING]
    return []


def process_replacements(tree: ast.AST) -> list[str]:
    """Each use of a `REPLACING` name (an attribute, a bare name, a `from` import, or by string through `getattr`, `vars`
    or `__dict__`) and each import of a `PROCESS_MODULES` module (plain, `from`, or a string given to
    `import_module`/`__import__`); one entry per use, so a count is checked."""
    found: list[str] = []
    for node in ast.walk(tree):
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        found += [name] if name in REPLACING else []
        found += _by_string(node)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found += [alias.name for alias in node.names if alias.name in REPLACING]
            found += _process_module(module) or [hit for alias in node.names for hit in _process_module(f"{module}.{alias.name}")]
        if isinstance(node, ast.Import):
            found += [hit for alias in node.names for hit in _process_module(alias.name)]
        if isinstance(node, ast.Call) and _called(node) in DYNAMIC_IMPORTS:
            found += [hit for text in _strings_of(node.args[:1]) for hit in _process_module(text)]
    return found


@pytest.mark.parametrize(("source", "names"), [
    ("os.execv(p, a)", ["execv"]), ("os.execvpe(p, a, e)", ["execvpe"]), ("from os import execl", ["execl"]),
    ("os.posix_spawnp(p, a, e)", ["posix_spawnp"]), ("pid = os.fork()", ["fork"]), ("os.forkpty()", ["forkpty"]),
    ("os.spawnv(m, p, a)", ["spawnv"]), ("hook = os.spawnlp", ["spawnlp"]), ("os.system(c)", ["system"]),
    ("os.popen(c)", ["popen"]), ("asyncio.create_subprocess_exec(p)", ["create_subprocess_exec"]),
    ("from asyncio import create_subprocess_shell", ["create_subprocess_shell"]),
    ("from concurrent.futures import ProcessPoolExecutor", ["ProcessPoolExecutor"]),
    ("_posixsubprocess.fork_exec(a)", ["fork_exec"]), ("import _posixsubprocess", ["_posixsubprocess"]),
    ("import concurrent.futures.process", ["concurrent.futures.process"]),
    ("from concurrent.futures import process", ["concurrent.futures.process"]),
    ("from concurrent.futures.process import _ExceptionWithTraceback", ["concurrent.futures.process"]),
    ('getattr(os, "fork")()', ["fork"]), ('vars(os)["execv"]', ["execv"]), ('os.__dict__["system"]', ["system"]),
    ("import pty", ["pty"]), ("import multiprocessing.pool", ["multiprocessing"]),
    ("from multiprocessing import Process", ["multiprocessing"]), ('importlib.import_module("pty")', ["pty"]),
    ('__import__("multiprocessing")', ["multiprocessing"]), ('import_module("concurrent.futures.process")', ["concurrent.futures.process"]),
    ("os.execv(p, a)\nos.execv(p, a)", ["execv", "execv"]),
    ('WORDS = ("execv", "fork")', []), ("executable = sys.executable", []), ("popen_held(argv)", []),
    ('getattr(os, "getcwd")', []), ('vars(o)["name"]', []), ("from concurrent.futures import ThreadPoolExecutor", []),
], ids=["execv", "execvpe", "from_os", "posix_spawnp", "fork", "forkpty", "spawnv", "spawn_reference", "system", "popen",
        "asyncio_exec", "asyncio_shell", "process_pool", "fork_exec", "posixsubprocess", "futures_process", "futures_process_from",
        "futures_process_member", "getattr", "vars", "dunder_dict", "pty", "mp_submodule", "mp_from", "import_module",
        "dunder_import", "import_module_futures", "twice", "words", "executable", "shelf_spawn", "getattr_other", "vars_other",
        "threads"])
def test_the_process_replacement_matcher_sees_uses_and_not_words(source: str, names: list[str]) -> None:
    assert sorted(process_replacements(ast.parse(source))) == sorted(names)


def test_nothing_forks_execs_or_spawns() -> None:
    """AGENTS.md: no spawn, fork or exec escape hatch in factory source or tests."""
    uses = Counter((name, str(path.relative_to(ROOT))) for path in FILES for name in process_replacements(ast.parse(path.read_text())))
    assert uses == Counter()


def _imported(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def test_only_the_dashboard_server_imports_the_http_server() -> None:
    """The one allowed importer of the standard library's HTTP code (`.importlinter` ignores exactly `dash_server -> http.server`),
    and the tests that use a client or a URL parser, are pinned here."""
    importers = {str(path.relative_to(ROOT)) for path in FILES
                 if any(name.split(".")[0] in {"http", "urllib", "socketserver"} for name in _imported(ast.parse(path.read_text())))}
    assert importers == {"src/taskloop/dash_server.py", "tests/cli/test_dash_server.py", "tests/cli/test_dash_composition.py",
                         "tests/rules/test_isolation.py"}
