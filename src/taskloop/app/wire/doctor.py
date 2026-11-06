"""`tl doctor`: what is off in the repo's setup for the loop, one line each, and the repo-profile report."""
import contextlib
import os
import shlex
import time
from pathlib import Path

from taskloop import contracts
from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.app.doctor import profiles
from taskloop.app.release import catalog, manifest
from taskloop.app.slots import watchdog
from taskloop.app.wire import hook
from taskloop.app.wire import slots as wslots
from taskloop.app.wire.slots import cfg_source
from taskloop.contracts import inputsets, runlife
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads, Git, Spawner
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.stores import ReposStore
from taskloop.domain.beads import matchers as beadlint
from taskloop.domain.checks.inputs import dead_globs
from taskloop.domain.lanes import pin
from taskloop.domain.layout import matchers as layout

Source = tuple[RepoProfile, str, str]


def git_warnings(repo: str, source: Source | None, git: Git) -> list[str]:
    """What is off in the repo's git setup for slots (tl-bxk.10.12) and in the globs of its checks."""
    out: list[str] = []
    if git.config_get(repo, "extensions.worktreeConfig").lower() != "true":
        out.append(f"extensions.worktreeConfig is off in {repo}: per-worktree settings (core.worktree, core.bare) then live in "
                   "the one .git/config every slot shares, so a stray one redirects all slots; `git config "
                   "extensions.worktreeConfig true` gives each worktree its own config file.")
    try:
        profile, _, commit = source or cfg_source(repo, git)
    except (SystemExit, OSError, ValueError):  # a bad profile is the profile report's to say
        return out
    files: list[str]
    try:
        files = [e.path for e in git.ls_tree(repo, commit, recursive=True)] if commit else git.ls_files(repo)
    except SlotGitError:
        files = []
    for c in profile.engine.checks:  # inputs globs that match no tracked file would cache a green over changed code
        ins = inputsets.expand(profile.engine, c.inputs)
        if not ins:
            out.append(f"check {c.id}: declares no inputs, so its result is keyed on the whole tree and base and is rerun whenever "
                       "anything moves; list the globs it reads (`inputs`, with `inputs_only` when they are complete).")
        for g in dead_globs(files, ins):
            out.append(f"check {c.id}: inputs glob {g} matches no tracked file, so the check is never cached; braces are "
                       "{a,b}, `*` stays in one folder, `**` crosses.")
    out += [f"engine.input_sets.{n} is named by no check (`inputs`, `exclude`, `when`) and not by engine.hatch: delete it."
            for n in inputsets.unused(profile.engine)]
    return out


def layout_warnings(repo: str, source: Source | None, git: Git) -> list[str]:
    """tl-9un.32, tl-9un.37: where the repo's checks leave tl's layout, and what of the factory sits in its tracked files. Read only."""
    try:
        profile = (source or cfg_source(repo, git))[0]
        files = git.ls_files(repo)
    except (SystemExit, OSError, ValueError, SlotGitError):  # a bad profile is the profile report's to say
        return []

    def read(path: str) -> str:
        try:
            return (Path(repo) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return layout.deviations(profile) + layout.leaks(files, read)


def bead_lint_warnings(repo: str, who: Identity, store: Beads | None = None) -> list[str]:
    """tl-f52: one line per open bead whose text cites material outside the repo (beadlint). [] when bd cannot be read."""
    try:
        beads = (store or bd_store(who.actor, repo)).find(BeadQuery(status="open"))
    except (BdCommandFailure, SystemExit, OSError, BdFailure):
        return []
    out: list[str] = []
    for b in beads:
        if b.issue_type == "epic" or "slot" in b.labels:
            continue
        r = beadlint.refs(b, repo)
        if r:
            cites = "; ".join(f"{k} {t[:60]}" for k, t in r[:3])
            out.append(f"bead {b.id}: {beadlint.REASON}: {cites}; inline the facts, or label it {beadlint.ESCAPE_LABEL} "
                       "if this is a false positive")
    return out


OWNERSHIP = "## Ownership"


def slot_warnings(repo: str, who: Identity, git: Git, now: float, spawner: Spawner | None = None) -> tuple[str, list[str]]:
    """(the slot table's one-line summary, its WARN lines): the slots as `tl status` and the dash list them, against config and folders."""
    try:
        table = wslots.slot_table(repo, who, git, now)
    except (SystemExit, OSError, ValueError, BdFailure) as err:
        return f"slots: not read ({err})", []
    states = ", ".join(f"{v.id} {v.state}" for v in table.slots) or "none"
    where = f"{table.source} {table.source_sha[:7]}".strip()
    warns = [f"slot {v.id} is {v.state}: {v.idle_why}" for v in table.slots if v.state == "dead"]
    warns += [f"slot {v.id} is above slots.count {table.configured} and still {v.state}" for v in table.slots
              if v.beyond_count and v.state not in ("free", "retiring")]
    if spawner is not None:  # tl-bxk.10.33.12: the liveness invariants, read only (the loop and the waiters heal)
        with contextlib.suppress(SystemExit, OSError, ValueError, BdFailure):
            warns += watchdog.lines(watchdog.look(wslots.slot_env(repo, spawner=spawner, git=git, who=who)))
    return f"slots: {table.configured} configured from {where}; {states}", warns


def launcher_problems(plugin_root: Path, env: Env) -> list[str]:
    """One finding for launchers still pointing at an older sibling cache version."""
    try:
        newest = hook.newest_install(plugin_root)
    except OSError:
        return []
    version = hook.version_key(newest.name)
    if not version:
        return []
    root = config_dir(env)
    stale = []
    for name, path in [("shim", root / "bin/tl"), *((n, ConfigDir(root).hooks_dir() / n) for n in hook.HOOK_NAMES)]:
        try:
            text = path.read_text(encoding="utf-8")
            words = [] if hook.RESOLVING_MARK in text else shlex.split(text, comments=True)  # a resolving shim is never stale
        except (OSError, ValueError):
            continue
        for word in words:
            try:
                relative = Path(word).relative_to(newest.parent)
            except ValueError:
                continue
            target = hook.version_key(relative.parts[0]) if relative.parts else ()
            if target and target < version:
                stale.append(name)
                break
    return [f"{', '.join(stale)} points at a version older than newest installed task-loop {newest.name}"] if stale else []


def path_link_line(env: Env) -> tuple[str, bool]:
    """(the doctor's line about the `tl` on PATH, True when a different `tl` is in the way)."""
    state, link = hook.link_state(env), hook.path_link(env)
    if state == "windows":
        return f"PATH tl: no link on Windows; run {config_dir(env) / 'bin' / 'tl'}", False
    on_path = str(link.parent) in (env.get("PATH") or "").split(os.pathsep)
    where = f"{link.parent} is {'on' if on_path else 'NOT on'} PATH"
    if state == "foreign":
        return f"PATH tl is not ours: {link}; {where}", True
    return f"PATH tl: {link} {'-> the shim' if state == 'ours' else 'is missing (the next session start links it)'}; {where}", False


def legacy_line(env: Env) -> str:
    """'' or a line naming the retired session index folder (SessionStart no longer writes it, nothing reads it): safe to delete by hand."""
    folder = config_dir(env) / "sessions"
    if not folder.is_dir():
        return ""
    return f"legacy: {folder} ({sum(1 for _ in folder.iterdir())} files) is the retired session index; nothing reads it, delete it"


def install_problems(plugin_root: Path, env: Env) -> list[str]:
    """What is wrong with the plugin install this tl runs from and the one Claude Code records as installed: a file that differs from
    MANIFEST.sha256 (named), an AGENTS.md without its ownership section. A source checkout has no manifest and is checked for none."""
    out = launcher_problems(plugin_root, env)
    try:
        agents = (plugin_root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        agents = ""
    if OWNERSHIP not in agents.splitlines():
        out.append(f"{plugin_root / 'AGENTS.md'} has no '{OWNERSHIP}' section (who may write the checkout, the cache, the ports)")
    claude = claude_dir(env)
    version = catalog.installed_version("task-loop", claude)
    installed = catalog.cache_dirs("task-loop", claude).get(version)
    if installed:
        out += [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)]
    return out


def run(plugin_root: Path, env: Env, git: Git, who: Identity, spawner: Spawner | None = None) -> int:
    repo = git.toplevel(".") or os.getcwd()
    if profiles.report(git, repo, ReposStore(ConfigDir(config_dir(env)))):  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = cfg_source(repo, git)
    _, base, commit = source
    print(f"config: .task-loop.json from base {base} at commit {commit}" if commit else
          f"config: .task-loop.json from working tree {repo} (base {base} unresolved; no commit read)")
    slot_line, slot_warns = slot_warnings(repo, who, git, time.time(), spawner)
    print(slot_line)
    link_line, foreign = path_link_line(env)
    if not foreign:
        print(link_line)  # a foreign `tl` is a WARN below
    warns = git_warnings(repo, source, git) + layout_warnings(repo, source, git) + bead_lint_warnings(repo, who) + slot_warns
    warns += [link_line] if foreign else []
    warns += [] if source[0].engine.writer_exec_allow else [
        "plan check argv unrestricted: the profile lists no engine.writer_exec_allow, so a planner's own check may run any command"]
    warns += [f"run {r} is lost: its process is gone and it recorded no end" for r in runlife.reconcile(who.config, time.time())]
    print(f"contracts: {Path(contracts.__file__).resolve().parent}")
    print(f"engine: {pin.describe(pin.families(source[0].engine.writer_family, []))}")
    for w in warns:
        print("WARN " + w)
    if legacy := legacy_line(env):
        print(legacy)
    fails = install_problems(plugin_root, env)
    for p in fails:
        print("FAIL " + p)
    if not warns and not fails:
        print("ok: no setup problems found in " + repo)
    return 1 if fails else 0



