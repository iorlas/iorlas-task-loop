"""A repos.json as the code reads it now (contracts/snapshots.py ReposIndex): each repo under its folder name, or `parent/name`
when two share one."""
import json
from pathlib import Path


def write_repos(file: Path | str, *repos: object) -> None:
    body: dict[str, dict[str, object]] = {}
    for r in repos:
        path = Path(str(r))
        name = path.name if path.name not in body else f"{path.parent.name}/{path.name}"
        body[name] = {"path": str(r), "added": 0.0}
    Path(file).write_text(json.dumps({"v": 2, "repos": body}), encoding="utf-8")
