"""Mandatory shelf contracts, established from bounded Python AST evidence."""

import ast
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from taskloop.shelf_digest.identities import Identities
from taskloop.shelf_digest.source import ReadFailure, SourceOpener


class FactName(StrEnum):
    TIMEOUT = "timeout"
    SUSPEND = "suspend"
    STARTED = "started"
    SUMMARY = "summary"
    USAGE = "usage"
    PARK = "park"


class FactFailureReason(StrEnum):
    EVIDENCE = "evidence"
    CONTRACT = "contract"


@dataclass(frozen=True)
class FactFailure:
    reason: FactFailureReason
    explanation: str


@dataclass(frozen=True)
class Evidence:
    package: str
    commit: str
    path: str
    start_line: int
    end_line: int
    sha256: str


@dataclass(frozen=True)
class Fact:
    name: FactName
    text: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Rule:
    package: str
    module: str
    symbol: str
    fragments: tuple[str, ...]
    ordered: bool = False


@dataclass(frozen=True)
class Contract:
    name: FactName
    text: str
    rules: tuple[Rule, ...]


CONTRACTS = (
    Contract(FactName.TIMEOUT, "run: wall timeout, 0=off; injected monotonic clock is for watchdogs.", (
        Rule("any-agent", "supervisor", "Supervisor._wait", (
            "time.time() + timeout if timeout else None", "time.time() >= end", "self.out.timed_out = True",
            "self._stop(p, killed, 'timeout')")),
        Rule("any-agent", "supervisor", "run", ("clock: Callable[[], float] = time.monotonic",)),
    )),
    Contract(FactName.SUSPEND, "Watchdog: suspend gap shifts start/last; wall timeout is unadjusted.", (
        Rule("any-agent", "supervisor", "Supervisor.__init__", (
            "watch.Watchdog(lim.first_event_s, hooks.idle_s or lim.silence_s, clock=clock, beat=hooks.beat)",)),
        Rule("any-agent", "watch", "Watchdog.poll", (
            "now = self.clock()", "gap = now - self.polled",
            "if gap > SLEEP_GAP_S:\n self.start += gap\n self.last += gap")),
    )),
    Contract(FactName.STARTED, "Register before exec: worker, started hook, live.started; callback failure cleans child.", (
        Rule("any-agent", "supervisor", "Supervisor.run", (
            "self.out.worker = worker", "self.hooks.started(worker)", "self.live.started(worker.pid)",
            "procs.spawn(spec.argv, spec.cwd, spec.env, registered=register)"), True),
        Rule("any-agent", "procs", "spawn", (
            "registered(worker)",
            "stream_proc.popen_registered(argv, registered=register, cwd=cwd, env=env, stderr=stderr, start_new_session=session)"), True),
        Rule("stream-proc", "registered", "popen_registered", (
            "registered(identity)", "permission_possible = True",
            "_send(control_write, struct.pack('!I', len(raw)) + raw, deadline)",
            "_abort(child, identity, error, permission_possible=permission_possible)"), True),
        Rule("stream-proc", "registered", "_abort", ("_cleanup(child)",)),
        Rule("stream-proc", "registered", "_cleanup", (
            "child.wait(timeout=0.2)", "child.kill()", "child.wait(timeout=2)", "stream.close()"), True),
    )),
    Contract(FactName.SUMMARY, "Summary(text,rc,res,vendor,stderr,work,check,stands,warnings,tail,data,facts,cost) settles outcomes; "
             "RunOutcome.summary; finish: harness summary,live.end; killed rc=0 -> -SIGKILL.", (
        Rule("any-agent", "protocol", "Summary", tuple(f"{name}: {kind} = {default}" for name, kind, default in (
            ("text", "str", "''"), ("rc", "int | None", "None"), ("res", "dict[str, Json]", "field(default_factory=dict)"),
            ("vendor", "str", "''"), ("stderr", "str", "''"), ("work", "bool", "False"), ("check", "bool", "True"),
            ("stands", "bool", "False"), ("warnings", "list[str]", "field(default_factory=list)"),
            ("tail", "str", "''"), ("data", "Json", "None"), ("facts", "dict[str, Json]", "field(default_factory=dict)"),
            ("cost", "float", "0.0")))),
        Rule("any-agent", "supervisor", "RunOutcome", ("summary: Summary = field(default_factory=Summary)",)),
        Rule("any-agent", "supervisor", "Supervisor.finish", (
            "if killed and rc == 0:\n rc = -signal.SIGKILL",
            "o.summary = self.hx.summary(rc, out, err, self.turn.stop, o.timed_out)",
            "self.live.end(end_status(o.timed_out, self.now.why if self.now.why == 'hung' else None, self.turn.stop, rc), "
            "o.summary.cost or None)"), True),
    )),
    Contract(FactName.USAGE, "TurnDone.usage: Tokens|None; in_,cached,out,cache_write: int|None.", (
        Rule("any-agent", "events", "TurnDone", ("usage: Tokens | None",)),
        Rule("any-agent", "events", "Tokens", (
            "in_: int | None", "cached: int | None", "out: int | None", "cache_write: int | None = None")),
    )),
    Contract(FactName.PARK, "park detaches/cleans; keep_ignored preserves ignored files; "
             "tracked collision refuses before change; exclude is checkout-local.", (
        Rule("git-porcelain", "real_write", "park", (
            "if keep_ignored:\n _keep_ignored(wt, real_checkout.resolve_commit(wt, base))",
            "wt.run('checkout', '-q', '--detach', base)", "_clean(wt, clean_keep)"), True),
        Rule("git-porcelain", "real_write", "_keep_ignored", (
            "wt.run('ls-files', '-z', '-o', '-i', '--exclude-standard', '--directory')",
            "t == i or (i.endswith('/') and t.startswith(i))",
            "raise IgnoredFilesWouldBeOverwritten(msg, clash)",
            "exclude_worktree(wt, [literal_pattern(p) for p in ignored])"), True),
        Rule("git-porcelain", "real_write", "exclude_worktree", (
            "target = real_read.git_dir_of(wt) / 'worktree-exclude'",
            "wt.run('config', '--worktree', 'core.excludesFile', str(target))")),
    )),
)


def _symbol(tree: ast.Module, name: str) -> ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef:
    body = tree.body
    result: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for part in name.split("."):
        matches = [node for node in body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == part]
        if len(matches) != 1:
            raise ValueError(f"Missing or ambiguous declaration {name}")
        result = matches[0]
        body = result.body
    if result is None:
        raise ValueError("Empty declaration")
    return result


def _fragment(text: str) -> ast.AST:
    node = ast.parse(text).body[0]
    if isinstance(node, ast.Expr):
        return node.value
    return node


def _parameter_matches(symbol: ast.FunctionDef | ast.AsyncFunctionDef, expected: ast.AnnAssign) -> bool:
    if not isinstance(expected.target, ast.Name) or expected.value is None:
        return False
    for arg, default in zip(symbol.args.kwonlyargs, symbol.args.kw_defaults, strict=True):
        if arg.arg == expected.target.id and arg.annotation is not None and default is not None:
            return ast.dump(arg.annotation) == ast.dump(expected.annotation) and ast.dump(default) == ast.dump(expected.value)
    return False


def check_rule(tree: ast.Module, rule: Rule) -> tuple[int, int]:
    """Require concrete operations/fields and, where specified, their execution order."""
    symbol = _symbol(tree, rule.symbol)
    positions = []
    for fragment in rule.fragments:
        expected = _fragment(fragment)
        # A default on a callable parameter lives in arguments, rather than AnnAssign.
        if isinstance(expected, ast.AnnAssign) and isinstance(symbol, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _parameter_matches(symbol, expected):
                raise ValueError(f"{rule.symbol}: incompatible parameter {fragment}")
            continue
        candidates = list(ast.walk(symbol))
        matches = [node for node in candidates if ast.dump(node) == ast.dump(expected)]
        if not matches:
            raise ValueError(f"{rule.symbol}: missing contract operation {fragment}")
        positions.append(min(node.lineno for node in matches if isinstance(node, (ast.stmt, ast.expr))))
    if rule.ordered and positions != sorted(positions):
        raise ValueError(f"{rule.symbol}: incompatible operation order")
    return symbol.lineno, symbol.end_lineno or symbol.lineno


def collect_facts(identities: Identities, opener: SourceOpener) -> tuple[Fact, ...] | FactFailure:
    """Read only immutable source; a missing or incompatible contract fails closed."""
    packages = {item.name: item for item in identities.packages}
    result = []
    try:
        for contract in CONTRACTS:
            evidence = []
            for rule in contract.rules:
                identity = packages[rule.package]
                source = opener(identity.commit)
                if isinstance(source, ReadFailure) or source.commit != identity.commit:
                    raise ValueError(f"{rule.package}: unavailable or mismatched source commit")
                module = rule.package.replace("-", "_")
                path = f"{identity.subdirectory}/src/{module}/{rule.module}.py"
                data = source.read(path)
                if isinstance(data, ReadFailure):
                    raise ValueError(data.explanation)
                check_rule(ast.parse(data), rule)
                evidence.append(Evidence(identity.name, identity.commit, path, 1, len(data.splitlines()), sha256(data).hexdigest()))
            result.append(Fact(contract.name, contract.text, tuple(dict.fromkeys(evidence))))
    except (ValueError, KeyError, SyntaxError, UnicodeError) as error:
        return FactFailure(FactFailureReason.CONTRACT, f"Cannot establish shelf facts: {error}")
    return tuple(result)
