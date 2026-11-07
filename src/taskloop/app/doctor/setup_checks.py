"""Setup checks for the doctor's report, using caller-supplied profile facts."""
import os
import shlex
import shutil
from pathlib import Path

from tlkernel import inputsets
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.beadsport import BdFailure, BeadQuery, Beads
from tlkernel.config import RepoProfile
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir
from tlkernel.slots import SlotGitError

from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import disk, install
from taskloop.domain.beads import matchers as beadlint
from taskloop.domain.checks.inputs import dead_globs
from taskloop.domain.layout import matchers as layout

Source = tuple[RepoProfile, str, str]


def git_warnings(repo: str, source: Source, git: Git) -> list[str]:
    """What is off in the repo's git setup for slots (tl-bxk.10.12) and in the globs of its checks."""
    out: list[str] = []
    if git.config_get(repo, "extensions.worktreeConfig").lower() != "true":
        out.append(f"extensions.worktreeConfig is off in {repo}: per-worktree settings (core.worktree, core.bare) then live in "
                   "the one .git/config every slot shares, so a stray one redirects all slots; `git config "
                   "extensions.worktreeConfig true` gives each worktree its own config file.")
    profile, _, commit = source
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


def layout_warnings(repo: str, source: Source, git: Git) -> list[str]:
    """tl-9un.32, tl-9un.37: where the repo's checks leave tl's layout, and what of the factory sits in its tracked files. Read only."""
    try:
        profile = source[0]
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


def launcher_problems(plugin_root: Path, env: Env) -> list[str]:
    """One finding for launchers still pointing at an older sibling cache version."""
    try:
        newest = install.newest_install(plugin_root)
    except OSError:
        return []
    version = install.version_key(newest.name)
    if not version:
        return []
    root = config_dir(env)
    stale = []
    for name, path in [("shim", root / "bin/tl"), *((n, ConfigDir(root).hooks_dir() / n) for n in install.HOOK_NAMES)]:
        try:
            text = path.read_text(encoding="utf-8")
            words = [] if install.RESOLVING_MARK in text else shlex.split(text, comments=True)  # a resolving shim is never stale
        except (OSError, ValueError):
            continue
        for word in words:
            try:
                relative = Path(word).relative_to(newest.parent)
            except ValueError:
                continue
            target = install.version_key(relative.parts[0]) if relative.parts else ()
            if target and target < version:
                stale.append(name)
                break
    return [f"{', '.join(stale)} points at a version older than newest installed task-loop {newest.name}"] if stale else []


def path_link_line(env: Env) -> tuple[str, bool]:
    """(the doctor's line about the `tl` on PATH, True when a different `tl` is in the way)."""
    state, link = install.link_state(env), install.path_link(env)
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


def disk_run(config: ConfigDir) -> int:
    """`tl doctor --disk`: the config folder's bytes by area and the free space of its volume. 1 when the volume runs low."""
    root = config.root
    lines = disk.report(root, shutil.disk_usage(root if root.is_dir() else root.parent).free, disk.read_samples(config))
    print("\n".join(lines))
    return 1 if any(ln.startswith("WARN") for ln in lines) else 0

