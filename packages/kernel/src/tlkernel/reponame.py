"""The name a repo goes by in repos.json: the origin's `owner/name`, or the folder name when there is no origin. Read from the git
config files directly, so no process runs and a folder that is not a repo still gets a name."""
from pathlib import Path


def _gitdir(path: Path) -> Path | None:
    """The common git dir of `path` (a worktree's `.git` file points to its own, which names the common one)."""
    dot = path / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    own = (path / text[len("gitdir:"):].strip()).resolve()
    try:
        common = (own / (own / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        return own
    return common


def origin_url(path: str) -> str | None:
    git = _gitdir(Path(path))
    if git is None:
        return None
    try:
        lines = (git / "config").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    inside = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("["):
            inside = line.replace(" ", "") == '[remote"origin"]'
        elif inside and line.replace(" ", "").startswith("url="):
            return line.split("=", 1)[1].strip()
    return None


def repo_name(path: str) -> str:
    """`owner/name` of the origin, else the folder name."""
    url = origin_url(path)
    if url:
        parts = [p for p in url.rstrip("/").removesuffix(".git").replace(":", "/").split("/") if p]
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
    return Path(path).name
