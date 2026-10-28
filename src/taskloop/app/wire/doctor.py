"""`tl doctor`: what is off in the repo's setup for the loop, one line each, and the repo-profile report."""
import os
from pathlib import Path

from taskloop import contracts
from taskloop.adapters import gitrepo
from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.gitrepo import git as real_git
from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import profiles
from taskloop.app.release import catalog, manifest
from taskloop.app.wire.slots import Git, cfg_source
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.domain.beads import matchers as beadlint
from taskloop.domain.checks.inputs import dead_globs

Source = tuple[RepoProfile, str, str]


def git_warnings(repo: str, source: Source | None = None, git: Git = gitrepo.git) -> list[str]:
    """What is off in the repo's git setup for slots (tl-bxk.10.12) and in the globs of its checks."""
    out: list[str] = []
    if git("config", "--get", "extensions.worktreeConfig", cwd=repo).lower() != "true":
        out.append(f"extensions.worktreeConfig is off in {repo}: per-worktree settings (core.worktree, core.bare) then live in "
                   "the one .git/config every slot shares, so a stray one redirects all slots; `git config "
                   "extensions.worktreeConfig true` gives each worktree its own config file.")
    try:
        profile, _, commit = source or cfg_source(repo, git)
    except (SystemExit, OSError, ValueError):  # a bad profile is the profile report's to say
        return out
    listing = git("ls-tree", "-r", "--name-only", "-z", commit, cwd=repo) if commit else git("ls-files", "-z", cwd=repo)
    files = [p for p in listing.split("\0") if p]
    for c in profile.engine.checks:  # inputs globs that match no tracked file would cache a green over changed code
        ins = [c.inputs] if isinstance(c.inputs, str) else list(c.inputs)
        for g in dead_globs(files, ins):
            out.append(f"check {c.id}: inputs glob {g} matches no tracked file, so the check is never cached; braces are "
                       "{a,b}, `*` stays in one folder, `**` crosses.")
    return out


def bead_lint_warnings(repo: str, store: Beads | None = None) -> list[str]:
    """tl-f52: one line per open bead whose text cites material outside the repo (beadlint). [] when bd cannot be read."""
    try:
        beads = (store or bd_store(repo)).find(BeadQuery(status="open"))
    except (SystemExit, OSError, BdFailure):
        return []
    out: list[str] = []
    for b in beads:
        if b.issue_type == "epic" or "slot" in b.labels:
            continue
        r = beadlint.refs(b, str(repo))
        if r:
            cites = "; ".join(f"{k} {t[:60]}" for k, t in r[:3])
            out.append(f"bead {b.id}: {beadlint.REASON}: {cites}; inline the facts, or label it {beadlint.ESCAPE_LABEL} "
                       "if this is a false positive")
    return out


OWNERSHIP = "## Ownership"


def install_problems(plugin_root: Path) -> list[str]:
    """What is wrong with the plugin install this tl runs from and the one Claude Code records as installed: a file that differs from
    MANIFEST.sha256 (named), an AGENTS.md without its ownership section. A source checkout has no manifest and is checked for none."""
    out: list[str] = []
    try:
        agents = (plugin_root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        agents = ""
    if OWNERSHIP not in agents.splitlines():
        out.append(f"{plugin_root / 'AGENTS.md'} has no '{OWNERSHIP}' section (who may write the checkout, the cache, the ports)")
    version = catalog.installed_version("task-loop")
    installed = catalog.cache_dirs("task-loop").get(version)
    if installed:
        out += [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)]
    return out


def run(plugin_root: Path) -> int:
    repo = real_git("rev-parse", "--show-toplevel") or os.getcwd()
    if profiles.report(repo, ConfigDir(config_dir()).repos()):  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = cfg_source(repo)
    _, base, commit = source
    print(f"config: .task-loop.json from base {base} at commit {commit}" if commit else
          f"config: .task-loop.json from working tree {repo} (base {base} unresolved; no commit read)")
    warns = git_warnings(repo, source) + bead_lint_warnings(repo)
    print(f"contracts: {Path(contracts.__file__).resolve().parent}")
    for w in warns:
        print("WARN " + w)
    fails = install_problems(plugin_root)
    for p in fails:
        print("FAIL " + p)
    if not warns and not fails:
        print("ok: no setup problems found in " + repo)
    return 1 if fails else 0



