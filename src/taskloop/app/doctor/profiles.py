"""One repo's bad .task-loop.json is that repo's problem: a RED row naming the file and the key, never a traceback and never another
repo's. Doctor, `tl loop status` and anything that walks the registered repos ask here before loading a profile."""
import json
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import config

FILE = ".task-loop.json"


def red_row(repo: str | Path) -> str:
    """"" when the repo's profile loads (or it has none); else `RED <repo>: <file>: <what is wrong, with the key>`."""
    path = Path(repo) / FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        config.load(json.loads(text))
    except json.JSONDecodeError as e:
        return f"RED {repo}: {path}: not JSON: {e}"
    except config.ConfigError as e:
        return f"RED {repo}: {path}: {e}"
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
    for row in ([mine] if mine else []) + red_rows(registered(repos_file), but=repo):
        say(row)
    return bool(mine)
