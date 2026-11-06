"""One repo's bad .task-loop.json is that repo's problem: a RED row naming the file and the key, never a traceback and never another
repo's. Doctor, `tl loop status` and anything that walks the registered repos ask here before loading a profile."""
import json
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import profile_at
from taskloop.adapters.gitmemo import ref_files
from taskloop.adapters.gitrepo import Sig, git_dirs, is_dir_sig, sig
from taskloop.contracts import config
from taskloop.contracts.ports import Git
from taskloop.contracts.rowstores import ReposStore
from taskloop.contracts.slots import NotARepo, SlotGitError

FILE = profile_at.FILE


def _base_name(repo: str | Path) -> str:
    """The base ref the working tree's profile names (engine.base), the default when it names none or does not parse."""
    try:
        engine = (profile_at.raw_in(repo) or {}).get("engine")
        name = engine.get("base") if isinstance(engine, dict) else None
    except (OSError, ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else config.RepoProfile().engine.base


def stamp(repo: str | Path) -> tuple[str, tuple[Sig, ...]] | None:
    """Files deciding `source`, without Git: checkout identity, profile's base choice, loose and packed refs.

    Unknown revision expressions and ref backends have no stamp; callers must use a bounded fallback cache.
    """
    dirs = git_dirs(repo)
    files = ref_files(("rev-parse", _base_name(repo) + "^{commit}"), dirs) if dirs else None
    if dirs is None or files is None:
        return None
    gd, common, dot_git = dirs
    pending = files[2:]  # packed-refs and shallow need signatures only
    seen = set(pending)
    for _ in range(8):
        targets: list[Path] = []
        for path in pending:
            try:
                text = path.read_text(encoding="utf-8").strip()
            except (OSError, ValueError):
                continue
            if text.startswith("ref:"):
                name = text[4:].strip()
                if not name.startswith("refs/") or ".." in Path(name).parts:
                    return None
                target = common / name
                if target in seen:
                    continue
                seen.add(target)
                targets.append(target)
        files.extend(targets)
        if not targets:
            break
        pending = targets
    else:
        return None
    return str(gd), (is_dir_sig(dot_git), sig(gd / "commondir"), sig(Path(repo) / FILE), *(sig(f) for f in files))


def source(git: Git, repo: str | Path) -> tuple[str, str]:
    """(the profile text, where it came from): what the loop reads, the profile as committed on the base ref ("base <sha7>"),
    the working tree's copy ("working tree") only when the base does not resolve here. ("", ...) when there is no file."""
    try:
        commit = git.rev_parse(str(repo), _base_name(repo) + "^{commit}")
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


def red_row(git: Git, repo: str | Path) -> str:
    """"" when the repo's profile loads (or it has none); else `RED <repo>: <file> (<source>): <what is wrong, with the key>`."""
    text, src = source(git, repo)
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


def registered(repos: ReposStore) -> list[str]:
    """The repos `tl register` knows that still exist."""
    return [r for r in repos.known() if Path(r).is_dir()]


def red_rows(git: Git, repos: list[str], but: str = "") -> list[str]:
    """A RED row for every repo of `repos` (but `but`) whose profile is bad."""
    return [row for r in repos if r != but and (row := red_row(git, r))]


def report(git: Git, repo: str, repos_file: ReposStore, say: Callable[[str], None] = print) -> bool:
    """Say this repo's red row (if any) and the other registered repos'; True when THIS repo's profile is bad."""
    mine = red_row(git, repo)
    say(f"profile: {repo} read from {source(git, repo)[1]}")
    for row in ([mine] if mine else []) + red_rows(git, registered(repos_file), but=repo):
        say(row)
    return bool(mine)
