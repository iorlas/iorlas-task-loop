"""The one place a repo's `.task-loop.json` is opened: a commit or tree through the Git port, or a working tree's file."""
import json
from pathlib import Path

from taskloop.contracts import config
from taskloop.contracts.gitport import Git
from taskloop.contracts.slots import SlotGitError

FILE = ".task-loop.json"


def object_of(text: str) -> dict[str, object]:
    """The profile's JSON object; ValueError when it is not one."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the profile must be a JSON object")
    return data


def raw_at(git: Git, repo: str, rev: str) -> dict[str, object] | None:
    """The profile committed at `rev` (a commit or a tree), parsed but not yet typed; None when the commit has no profile.
    SlotGitError when git cannot answer, ValueError when the file is not a JSON object."""
    try:
        text = git.show(repo, rev, FILE)
    except SlotGitError:
        try:
            if not git.ls_tree(repo, rev, FILE):
                return None
        except SlotGitError:
            pass  # absence was not established: the original read error stands
        raise
    return object_of(text)


def profile_at(git: Git, repo: str, rev: str) -> config.RepoProfile | None:
    """The typed profile committed at `rev`, None when there is none; ConfigError for a key it does not know."""
    data = raw_at(git, repo, rev)
    return None if data is None else config.load(data)


def raw_in(repo: str | Path) -> dict[str, object] | None:
    """The profile in the working tree's file, parsed but not yet typed; None when there is no file. OSError or ValueError when it
    cannot be read."""
    try:
        return object_of((Path(repo) / FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
