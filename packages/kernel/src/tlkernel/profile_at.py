"""The one place a repo's `.task-loop.json` is opened: a commit or tree through the GateGit port, or a working tree's file."""
import json
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from tlkernel import config
from tlkernel.gitport import GateGit, Git
from tlkernel.slots import NotARepo, SlotGitError

FILE = ".task-loop.json"


def object_of(text: str) -> dict[str, object]:
    """The profile's JSON object; ValueError when it is not one."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the profile must be a JSON object")
    return data


def raw_at(git: GateGit, repo: str, rev: str) -> dict[str, object] | None:
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


def profile_at(git: GateGit, repo: str, rev: str) -> config.RepoProfile | None:
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


def typed(data: object, say_to: TextIO | None = None) -> config.RepoProfile:
    """Validate an already decoded profile, preserving the config loader's diagnostics."""
    return config.load(data, say_to=say_to)


def parse(text: str, say_to: TextIO | None = None) -> config.RepoProfile:
    """Decode and validate profile text, including the loader's handling of non-objects."""
    return typed(json.loads(text), say_to=say_to)


def typed_in(repo: str | Path, say_to: TextIO | None = None) -> config.RepoProfile:
    """The working profile, with defaults when absent and object validation before typing."""
    return typed(raw_in(repo) or {}, say_to=say_to)


def typed_file(path: Path, say_to: TextIO | None = None) -> config.RepoProfile:
    """Validate an existing profile file; absence remains a read error."""
    return parse(path.read_text(encoding="utf-8"), say_to=say_to)


def source(git: Git, repo: str, base: str | None) -> tuple[dict[str, object], str]:
    """The base profile and resolved commit, falling back locally only if base is unresolved."""
    try:
        commit = git.rev_parse(repo, base + "^{commit}") if base else ""
    except NotARepo:
        commit = ""
    path = Path(repo) / FILE
    if commit:
        try:
            return raw_at(git, repo, commit) or {}, commit
        except (SlotGitError, ValueError) as err:
            raise config.ProfileReadError(str(path), commit, err) from err
    try:
        return raw_in(repo) or {}, ""
    except (OSError, ValueError) as err:
        raise config.ProfileReadError(str(path), "", err) from err


def base_name(repo: str | Path) -> str:
    """The diagnostic base choice, defaulting for invalid, absent or empty names."""
    try:
        engine = (raw_in(repo) or {}).get("engine")
        name = engine.get("base") if isinstance(engine, dict) else None
    except (OSError, ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else config.RepoProfile().engine.base


def working_engine(repo: str, loader: Callable[[object], config.RepoProfile]) -> config.EngineConfig:
    """Load the check command's working profile with its established missing-file diagnostics."""
    path = Path(repo) / FILE
    try:
        data = raw_in(repo)
    except (OSError, ValueError) as e:
        raise SystemExit(f"tl check: cannot read {path}: {e}") from None
    if data is None:
        raise SystemExit(f"tl check: cannot read {path}: no such file")
    return loader(data).engine


def diagnostic_source(git: Git, repo: str | Path) -> tuple[str, str]:
    """Doctor text and source labels, retaining its tolerant read behavior."""
    try:
        commit = git.rev_parse(str(repo), base_name(repo) + "^{commit}")
    except NotARepo:
        commit = ""
    if commit:
        try:
            text = git.show(str(repo), commit, FILE).strip()
        except SlotGitError:
            text = ""
        return text, f"base {commit[:7]}"
    try:
        return (Path(repo) / FILE).read_text(encoding="utf-8"), "working tree"
    except OSError:
        return "", "working tree"
