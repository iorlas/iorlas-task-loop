"""`tl doctor`'s guard rails of main, composed: the hook files and `gh api` reads (guard_rails.py judges them), as FAIL lines; and
`--print-guard-rails`. The root only calls `report` and `print_calls`."""
import os
import shlex
import sys
from pathlib import Path

from taskloop.adapters import landlock
from taskloop.app.doctor import guard_rails
from taskloop.contracts.gitport import Git
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.procport import Spawner
from taskloop.contracts.slots import MissingRemote


def github_slug(git: Git, repo: str) -> str:
    """owner/name of the repo's origin on github.com, '' for any other remote or none."""
    try:
        url = git.remote_url(repo, "origin")
    except MissingRemote:
        return ""
    host, _, path = landlock.canonical_remote(url).partition("/")
    return path if host == "github.com" and path.count("/") == 1 else ""


def expected_pre_push(template: str, install: Path | None, config: ConfigDir) -> str:
    """The text tl's setup writes for the pre-push dispatcher ('' when no install can be read)."""
    if install is None:
        return ""
    text = template.replace("{name}", "pre-push")
    for key, path in (("{hook}", install / "hooks" / "hook.py"), ("{tl}", config.root / "bin" / "tl")):
        text = text.replace(key, shlex.quote(str(path)))
    return text


def report(config: ConfigDir, template: str, install: Path | None, git: Git, repo: str, spawner: Spawner | None,
           checks: list[str]) -> list[str]:
    """The FAIL lines (printed here) of hook drift and, on a github.com origin, of the ruleset and branch protection. No spawner (a test
    that runs no process): nothing is read."""
    if spawner is None:
        return []
    found = guard_rails.hook_findings(config.hooks_dir(), expected_pre_push(template, install, config),
                                      [(c.path, git.config_get(c.path, "core.hooksPath")) for c in git.checkouts(repo)])
    if slug := github_slug(git, repo):
        found += guard_rails.ruleset_findings(lambda path: spawner.run(["gh", "api", path], cwd=repo, timeout_s=60), slug, checks)
    for line in found:
        print("FAIL " + line)
    return found


def print_calls(git: Git) -> int:
    slug = github_slug(git, git.toplevel(".") or os.getcwd())
    if not slug:
        print("origin is not a github.com repo: no guard rails to print")
        return 1
    sys.stdout.write(guard_rails.print_calls(slug))
    return 0
