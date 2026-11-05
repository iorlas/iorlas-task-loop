"""`tl setup --plan`: what this machine, host and repo still need before task-loop can work. Read-only: it looks, and returns the checks,
the fixes that are safe to make by themselves and the questions only the owner can answer. Nothing is created, written or linked here."""
import contextlib
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from taskloop.adapters import delegate as dg
from taskloop.app.wire import doctor, hook, slots
from taskloop.contracts.env import Env
from taskloop.contracts.paths import ConfigDir, default_root


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Fix:
    id: str
    what: str


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    choices: list[str]
    default: str
    why: str


@dataclass(frozen=True)
class Plan:
    checks: list[Check] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)


def machine(plugin_root: Path, env: Env) -> Plan:
    """The per-user part: the config folder, the shim, the `tl` on PATH and the git hooks. Every fix here is idempotent and safe."""
    root = default_root(env)
    checks = [Check("config", root.is_dir(), str(root))]
    fixes: list[Fix] = []
    shim = root / "bin" / "tl"
    text = shim.read_text(encoding="utf-8") if shim.is_file() else ""
    if hook.RESOLVING_MARK in text:
        checks.append(Check("shim", True, f"{shim} picks the newest install at run time"))
    else:
        checks.append(Check("shim", False, f"{shim} is " + ("an old fixed-path shim" if text else "missing")))
        fixes.append(Fix("shim", "write the shim that resolves the newest installed version"))
    state, link = hook.link_state(env), hook.path_link(env)
    checks.append(Check("path-link", state in ("ours", "windows"), f"{link}: {state}"))
    if state == "missing" and link.parent.parent.is_dir():
        fixes.append(Fix("path-link", f"link {link} to the shim"))
    names = [n for n in hook.HOOK_NAMES if not (ConfigDir(root).hooks_dir() / n).is_file()]
    problems = doctor.launcher_problems(plugin_root, env)
    checks.append(Check("githooks", not names and not problems, f"{len(hook.HOOK_NAMES) - len(names)}/{len(hook.HOOK_NAMES)} present"
                        + "".join(f"; {p}" for p in problems)))
    if names or problems:
        fixes.append(Fix("githooks", "write the git hooks (pre-push asks the delivery judge) into " + str(ConfigDir(root).hooks_dir())))
    checks.append(accounts_check())
    return Plan(checks, fixes)


def accounts_check() -> Check:
    """Worker accounts: at least one enabled lane that is ready. The login itself is the owner's (`tl accounts` names each fix)."""
    try:
        rows = dg.accounts()
    except (ValueError, SystemExit, OSError) as e:
        return Check("accounts", False, f"delegate has no account state yet: {e}")
    ready = [r.lane for r in rows if r.enabled and r.ready]
    return Check("accounts", bool(ready), ", ".join(ready) + " ready" if ready else "no enabled lane is ready; run `tl accounts`")


def stacks(repo: Path) -> dict[str, str]:
    """{stack: the file that shows it} for the repo's top folder: what the setup questions are tailored by."""
    marks = {"unity": "ProjectSettings/ProjectVersion.txt", "python": "pyproject.toml", "node": "package.json", "just": "justfile"}
    found = {name: mark for name, mark in marks.items() if (repo / mark).is_file()}
    nested = next(repo.glob("*/" + marks["unity"]), None)  # a Unity project one folder down (lifesim keeps it in client/)
    return found if "unity" in found or nested is None else {**found, "unity": str(nested.relative_to(repo))}


def profile_problem(profile: Path) -> str:
    """'' when the profile loads, else why not (the loader exits naming the key; its message is caught, not printed)."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            slots.load_profile(json.loads(profile.read_text(encoding="utf-8")))
    except (SystemExit, ValueError, OSError) as e:
        return (err.getvalue().strip() or str(e) or "unreadable")[:300]
    return ""


def repo_part(repo: Path) -> Plan:
    """The repo's part: its .task-loop.json (loads? stale?) and, when there is none, the questions that write one."""
    profile, found = repo / ".task-loop.json", stacks(repo)
    checks = [Check("stack", True, ", ".join(f"{k} ({v})" for k, v in found.items()) or "none recognised")]
    if profile.is_file():
        problem = profile_problem(profile)
        return Plan([*checks, Check("profile", not problem, problem or f"{profile} loads")])
    checks.append(Check("profile", False, f"{profile} does not exist"))
    asks: list[Question] = []
    if "unity" in found:
        asks.append(Question("unity-lease", "Unity project found: serialize editor runs with a concurrency lease?", ["yes", "no"], "yes",
                             "two editors on one project corrupt its Library; a lease makes slots take turns; yes also writes host.json"))
    if "just" in found:
        asks.append(Question("gate", "Is `just check` the repo gate?", ["yes", "no"], "yes", "the command a bead must pass to land"))
    return Plan(checks, [], asks)


def plan(plugin_root: Path, env: Env, repo: Path | None) -> Plan:
    parts = [machine(plugin_root, env)] + ([repo_part(repo)] if repo else [])
    return Plan([c for p in parts for c in p.checks], [f for p in parts for f in p.fixes], [q for p in parts for q in p.questions])


def render(p: Plan) -> str:
    lines = [f"{'ok  ' if c.ok else 'TODO'} {c.id}: {c.detail}" for c in p.checks]
    lines += [f"fix  {f.id}: {f.what}" for f in p.fixes]
    lines += [f"ask  {q.id}: {q.text} [{'/'.join(q.choices)}] default {q.default} ({q.why})" for q in p.questions]
    return "\n".join(lines or ["nothing to do"])


def as_json(p: Plan) -> str:
    return json.dumps(asdict(p), indent=2)
