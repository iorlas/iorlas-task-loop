"""A repos.json as the code reads it now (contracts/snapshots.py ReposIndex): each repo under its folder name."""
import json
from pathlib import Path


def write_repos(file: Path | str, *repos: object) -> None:
    body = {Path(str(r)).name: {"path": str(r), "added": 0.0} for r in repos}
    Path(file).write_text(json.dumps({"v": 2, "repos": body}), encoding="utf-8")
