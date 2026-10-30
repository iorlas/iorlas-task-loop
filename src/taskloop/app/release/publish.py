"""After main is pushed: the marketplace entry, the tags, the install and its check."""
import json
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters.ident import claude_dir
from taskloop.adapters.versionfile import NoVersion, entry_offset, set_version
from taskloop.app.release.shell import Abort, Shell, fetch_or_abort
from taskloop.contracts.ids import MARKETPLACE
from taskloop.contracts.slots import SlotGitError

PLUGIN = ".claude-plugin/plugin.json"
MARKET = ".claude-plugin/marketplace.json"
NAME = "iorlas-task-loop"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def bump_marketplace(market: Path, version: str, sh: Shell) -> None:
    git = sh.port
    d = str(market)
    fetch_or_abort(git, market)
    git_must(lambda: git.merge_ff(d, "origin/main"), market)
    f = market / MARKET
    text = f.read_text(encoding="utf-8")
    at = entry_offset(text, NAME)
    if at is None:
        raise Abort(f"{f} has no {NAME} entry")
    try:
        text = set_version(text, version, at)
    except NoVersion as e:
        raise Abort(f"could not set {NAME}'s version in {f}: {e}") from None
    entry = [p for p in json.loads(text)["plugins"] if p.get("name") == NAME]
    if not entry or entry[0].get("version") != version:
        raise Abort(f"could not set {NAME}'s version in {f}")
    f.write_text(text, encoding="utf-8")
    git_must(lambda: git.commit_tracked(d, f"{NAME} {version}{TRAILER}"), market)
    try:
        git.push(d, "origin", "HEAD:main")
    except SlotGitError:
        git_must(lambda: git.pull_rebase(d, "origin", "main"), market)
        git_must(lambda: git.push(d, "origin", "HEAD:main"), market)


def git_must[T](call: Callable[[], T], where: Path) -> T:
    """A git step of the release that must work: the port's error becomes the release's refusal."""
    try:
        return call()
    except SlotGitError as e:
        raise Abort(f"git failed in {where}:\n{e.tail}") from None


def tag(cwd: Path, name: str, what: str, sh: Shell) -> None:
    """Tag HEAD of `cwd` as `name` and push the tag. Called only after the branch push succeeded. A tag that cannot be made or
    pushed is a warning: the release is out and must not be reported as failed for it."""
    git = sh.port
    d = str(cwd)
    if git.rev_parse(d, "refs/tags/" + name):
        sh.say(f"warning: {what} already has the tag {name}; left as it is")
        return
    try:
        git.tag(d, name, "HEAD")
        git.push(d, "origin", "refs/tags/" + name)
    except SlotGitError as e:
        sh.say(f"warning: tag {name} in {what} failed: {e.tail[-300:]}")
    else:
        sh.say(f"tagged {name} in {what}")


def installed_manifest(version: str) -> Path:
    return claude_dir() / "plugins" / "cache" / MARKETPLACE / NAME / version / ".claude-plugin" / "plugin.json"


def install(cwd: Path, version: str, sh: Shell) -> None:
    """Update the marketplace and the plugin, then check the new version's cache dir exists. A silent failure (0.23.0: a git
    fetch-pack error with exit 0) leaves the old version installed: run both commands once more, then fail loudly."""
    cache = installed_manifest(version)
    cmds = [["claude", "plugin", "marketplace", "update", MARKETPLACE], ["claude", "plugin", "update", f"{NAME}@{MARKETPLACE}"]]
    failing: list[str] | None = None
    text = ""
    for attempt in (1, 2):
        for c in cmds:
            try:
                r = sh.run(c, cwd, check=False)
                rc, out = r.returncode, (r.stdout + r.stderr).strip()
            except OSError as e:
                rc, out = 127, str(e)
            if rc or c is cmds[-1]:
                failing, text = (c, out) if rc else (failing, out)
        if cache.is_file():
            sh.say(f"installed: {version} ({cache.parent.parent})")
            return
        sh.say(f"install attempt {attempt} left no {cache}; {'trying once more' if attempt == 1 else 'giving up'}")
    cmd = " ".join(failing or cmds[-1])
    why = f"the plugin install failed: {version} is not installed (no {cache}).\nfailing command: {cmd}\n{text[-1000:]}"
    raise Abort(why, version=version)
