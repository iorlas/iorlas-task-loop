"""The decision a call starts with: build the fleet, route, remember the lane choice (`decision`, shared by `next` and `run`), and what a
chosen
step runs on (`how`). The codex access flags and the repo's instruction files, which both lanes get the same, are here too."""

import json
import os
import random
import sys
from pathlib import Path
from typing import Final

from delegate.adapters import git
from delegate.app import env, onboard
from delegate.app.fleet import FleetBuilder, drift_warnings, mark_busy, settle_holds
from delegate.app.usage import READERS
from delegate.contracts.history import RunRow
from delegate.contracts.json_types import Json, as_str, obj
from delegate.contracts.routing import CallArgs, Run
from delegate.contracts.state import StateDoc
from delegate.contracts.stores import CheckpointStore
from delegate.domain.holds.book import HoldBook
from delegate.domain.lanes.lane import Lane
from delegate.domain.routing.dwell import DwellMemory
from delegate.domain.routing.router import Router

# Every codex run and resume gets these, so neither the user's config nor a repo file widens or narrows them. The sandbox has no network and
# writes only the working directory; a command it blocks may ask to run outside it, and Codex's automatic reviewer (a model, no human)
# approves or refuses that one command. Codex permission profiles would also block reads (~/.ssh), but an approved escalation there
# stays inside the sandbox, so Unity cannot run (codex-cli 0.162.1).
CODEX_ACCESS: Final = [
    "--ignore-user-config",
    "--ignore-rules",
    "-c",
    "sandbox_workspace_write.network_access=false",
    "-c",
    "sandbox_workspace_write.writable_roots=[]",
    "-c",
    "approval_policy=on-request",
    "-c",
    "approvals_reviewer=auto_review",
]


def codex_env(base: dict[str, str], cwd: str, sandbox: str, access: list[str] = CODEX_ACCESS) -> dict[str, str]:
    """The environment of a codex worker: uv must not reach for ~/.cache/uv (outside the sandbox: 'Operation not permitted', then a refused
    second escalation). A writing step caches in the git-ignored .task/ of its working folder, a reading one in no cache; with the network
    off
    uv stays offline."""
    out = dict(base)
    if sandbox == "workspace-write":
        out["UV_CACHE_DIR"] = str(Path(cwd) / ".task" / "uv-cache")
    else:
        out["UV_NO_CACHE"] = "1"
    if "sandbox_workspace_write.network_access=false" in access:
        out["UV_OFFLINE"] = "1"
    return out


def repo_dirs(cwd: str) -> list[Path]:
    """The folders from the repo root (or cwd outside a repo) down to cwd."""
    wd = Path(cwd).resolve()
    root = git.repo_root(wd)
    out = [wd]
    while out[-1] != root and out[-1].parent != out[-1] and root in out[-1].parents:
        out.append(out[-1].parent)
    return out[::-1]


def repo_instructions(cwd: str) -> list[Path]:
    """The repo's instruction files, the same for both lanes (Codex's own rule): in each folder from the root down to cwd, AGENTS.md, else
    CLAUDE.md."""
    found = []
    for d in repo_dirs(cwd):
        f = next((d / n for n in ("AGENTS.md", "CLAUDE.md") if (d / n).is_file()), None)
        if f:
            found.append(f)
    return found


def codex_isolation(cwd: str) -> list[str]:
    """Codex sees only what delegate sends plus the repo's instruction files: every skill it would list (its own system skills, the user's,
    the repo's .agents/skills) is turned off by path, and a repo with only CLAUDE.md is read as Claude would. Sub-agents cannot be turned
    off (codex 0.162.1: features.multi_agent=false and agents.max_depth=0 still let a brief that asks spawn one); NO_SUBAGENTS_RULE asks,
    and their
    tokens are counted as child threads."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    roots = [home / "skills", Path.home() / ".agents" / "skills"] + [
        d / x / "skills" for d in repo_dirs(cwd) for x in (".agents", ".codex")
    ]
    paths = sorted({str(f.resolve()) for r in roots if r.is_dir() for f in r.rglob("SKILL.md")})
    return [
        "-c",
        "skills.config=[" + ",".join(f"{{path={json.dumps(x)},enabled=false}}" for x in paths) + "]",
        "-c",
        'project_doc_fallback_filenames=["CLAUDE.md"]',
    ]


def how(lane: Lane, step: dict[str, Json], cfg: dict[str, Json], cwd: str | None = None, unattended: bool = False) -> dict[str, Json]:
    """What a step runs on. Unattended callers have no Agent tool, so the subscription lane runs `claude -p` on the logged-in account."""
    m = obj(obj(cfg["models"])[as_str(step["model"])])
    runner = obj(obj(cfg["lanes"])[lane.name])["runner"]
    wd = os.path.abspath(cwd) if cwd else os.getcwd()
    write = step.get("mode") == "write"
    if runner == "agent_tool" and unattended:
        runner = "claude_p"
    if runner == "claude_p":
        return {"kind": "claude_p", "model": m["api"], "write": write, "cap": step.get("cap", 2), "cwd": wd, "read_only": not write}
    if runner == "agent_tool":
        return {"kind": "agent_tool", "model": m["agent"], "cwd": wd}
    if runner == "opencode":
        return {"kind": "opencode", "model": m["api"], "write": write, "cwd": wd}
    sandbox = "workspace-write" if write else "read-only"
    iso = codex_isolation(wd)
    cli = [
        "codex",
        "exec",
        "-C",
        wd,
        "-s",
        sandbox,
        "-m",
        as_str(m["api"]),
        "-c",
        f"model_reasoning_effort={step['effort']}",
        *CODEX_ACCESS,
        *iso,
    ]
    if git.state(wd) is None:
        cli.append("--skip-git-repo-check")  # codex refuses a directory that is not a git work tree
    return {"kind": "codex", "model": m["api"], "cli": cli, "cwd": wd, "sandbox": sandbox, "isolation": iso}


def parse_json_arg(v: str | None) -> Json:
    if not v:
        return None
    if v == "-":
        v = sys.stdin.read()
    elif v.startswith("@"):
        v = Path(v[1:]).read_text(encoding="utf-8")
    try:
        return json.loads(v)
    except ValueError as e:
        sys.exit(f"route.py: --claude-usage is not valid JSON: {e}")


def busy_jitter() -> int:
    return random.randint(60, 120)


def fleet_builder(cfg: dict[str, Json]):
    return FleetBuilder(
        env.typed_routing(cfg),
        env.states(),
        env.history_store(),
        CheckpointStore(env.config_dir() / "health-checkpoint.json"),
        env.config_store(),
        READERS,
        lambda: onboard.configured_lanes(cfg),
    )


def call_args(a: env.Args, unattended: bool):
    return CallArgs(
        authored_by=a.authored_by,
        premium=a.premium,
        allow_degraded=a.allow_degraded,
        unattended=unattended,
        resume=getattr(a, "resume", None),
        cap=getattr(a, "cap", None),
        only_family=tuple(getattr(a, "only_family", None) or ()),
        engine_only=tuple(getattr(a, "engine_only", None) or ()),
        engine_only_advisory=bool(getattr(a, "engine_only_advisory", False)),
    )


RETRY_LOOKBACK_S = 6 * 3600


def decision(a: env.Args, cfg: dict[str, Json], unattended: bool = False, avoid: frozenset[tuple[str, str]] = frozenset()):
    """next and run share this: build the fleet, route, remember the lane choice. -> (d, lanes, warnings, t); d is the JSON answer of
    `next`."""
    t = env.now()
    st = env.load_state()
    routing = env.typed_routing(cfg)
    fleet = fleet_builder(cfg).build(st, t, parse_json_arg(a.claude_usage))
    warnings = drift_warnings(env.states(), fleet.lanes, st, t)
    _, st = settle_holds(env.states(), fleet.lanes, st, t)
    lanes = mark_busy(fleet.lanes, st, routing.settings, t, busy_jitter)
    args = call_args(a, unattended)
    if getattr(a, "task", None) and not args.resume:
        avoid |= frozenset(
            (r.lane, r.model)
            for r in env.history_store().rows(t - RETRY_LOOKBACK_S)
            if isinstance(r, RunRow) and r.ts <= t and r.task == a.task and r.role == a.role and r.outcome in ("timeout", "schema_invalid")
        )
    router = Router(routing, HoldBook(st.holds), st.prev, t)
    pick = router.route(a.role, args, lanes, st.refs.get(args.resume or ""), avoid)
    d = pick.as_dict()
    if isinstance(pick, Run):
        step: dict[str, Json] = {"model": pick.model, "effort": pick.effort, "mode": pick.mode}
        if pick.cap is not None or pick.pass_ == "resume":
            step["cap"] = pick.cap
        hw = d["how"] = how(lanes[pick.lane], step, cfg, a.cwd, unattended)
        if pick.pass_ != "resume":
            fam = lanes[pick.lane].family
            if args.cap:
                d["cap"] = hw["cap"] = args.cap if hw["kind"] == "claude_p" else hw.get("cap")

            def mark(s: StateDoc) -> None:
                new = DwellMemory(s.prev, routing.settings.min_dwell_minutes).note(fam, pick.lane, t)
                if new:
                    s.prev[fam] = new

            if sum(1 for lane in lanes.values() if lane.family == fam) > 1:
                env.update_state(mark)
    if fleet.offers:
        env.config_store().mark_offered(fleet.offers)
        d["notice"] = "not set up: " + ", ".join(fleet.offers) + " (route.py doctor)"
    return d, lanes, warnings, t


