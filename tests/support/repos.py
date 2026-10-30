"""A repos.json as the code reads it now (contracts/snapshots.py ReposIndex)."""
import json
from pathlib import Path


def write_repos(file: Path | str, *repos: object) -> None:
    Path(file).write_text(json.dumps({"v": 1, "repos": {str(r): {"added": 0.0} for r in repos}}), encoding="utf-8")
