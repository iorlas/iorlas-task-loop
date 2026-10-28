"""One repo's bad .task-loop.json is that repo's problem: a RED row naming the file and the key, never a traceback and never another
repo's. Doctor, `tl loop status` and anything that walks the registered repos ask here before loading a profile."""
import json
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters.gitenv import run_git
from taskloop.contracts import config

FILE = ".task-loop.json"


def _git(repo: str | Path, *args: str) -> str:
    r = run_git(repo, *args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def _base_name(repo: str | Path) -> str:
    """The base ref the working tree's profile names (engine.base), the default when it names none or does not parse."""
    try:
        engine = json.loads((Path(repo) / FILE).read_text(encoding="utf-8")).get("engine")
        name = engine.get("base") if isinstance(engine, dict) else None
    except (OSError, ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else config.RepoProfile().engine.base


def source(repo: str | Path) -> tuple[str, str]:
    """(the profile text, where it came from): what the loop reads, the profile as committed on the base ref ("base <sha7>"),
    the working tree's copy ("working tree") only when the base does not resolve here. ("", ...) when there is no file."""
    commit = _git(repo, "rev-parse", "--verify", "-q", _base_name(repo) + "^{commit}")
    if commit:
        return _git(repo, "show", f"{commit}:{FILE}"), f"base {commit[:7]}"
    try:
        return (Path(repo) / FILE).read_text(encoding="utf-8"), "working tree"
    except OSError:
        return "", "working tree"


def red_row(repo: str | Path) -> str:
    """"" when the repo's profile loads (or it has none); else `RED <repo>: <file> (<source>): <what is wrong, with the key>`."""
    text, src = source(repo)
    if not text:
        return ""
    where = f"{Path(repo) / FILE} ({src})"
    try:
        config.load(json.loads(text))
    except json.JSONDecodeError as e:
        if src != "working tree":  # the loop reads a base copy that is not JSON as {} (no profile): doctor agrees with it
            return ""
        return f"RED {repo}: {where}: not JSON: {e}"
    except config.ConfigError as e:
        return f"RED {repo}: {where}: {e}"
    return ""


def registered(repos_file: Path) -> list[str]:
    """The repos `tl register` knows that still exist."""
    try:
        listed = json.loads(repos_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in listed if isinstance(r, str) and Path(r).is_dir()] if isinstance(listed, dict) else []


def red_rows(repos: list[str], but: str = "") -> list[str]:
    """A RED row for every repo of `repos` (but `but`) whose profile is bad."""
    return [row for r in repos if r != but and (row := red_row(r))]


def report(repo: str, repos_file: Path, say: Callable[[str], None] = print) -> bool:
    """Say this repo's red row (if any) and the other registered repos'; True when THIS repo's profile is bad."""
    mine = red_row(repo)
    say(f"profile: {repo} read from {source(repo)[1]}")
    for row in ([mine] if mine else []) + red_rows(registered(repos_file), but=repo):
        say(row)
    return bool(mine)
