"""The bead tracker's own backup: once a UTC day a JSONL export of a repo's issues beside the factory snapshots (`<config>/backups/
bd-<repo key>-YYYYMMDD.jsonl`, seven kept), and once a UTC month a restore drill on the newest one. The drill reads the export back
(every line parses, the issue count is the one bd reported, bd still counts at least that many); it does not rebuild a Dolt database.
bd is a callable: argv -> (exit code, stdout, stderr)."""
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from tlkernel.factorybackup import backup_dir
from tlkernel.paths import ConfigDir

Bd = Callable[[list[str]], tuple[int, str, str]]
KEEP = 7


def exported(text: str) -> int | None:
    """The issue count in bd's "Exported N issues and M memories to <file>" line."""
    words = text.split("Exported ", 1)[-1].split() if "Exported " in text else []
    return int(words[0]) if words and words[0].isdigit() else None


def _name(key: str, now: float) -> Path:
    return Path(f"bd-{key}-{datetime.fromtimestamp(now, UTC):%Y%m%d}.jsonl")


def exports(cfg: ConfigDir, key: str) -> list[Path]:
    """The repo's exports, newest first."""
    return sorted(backup_dir(cfg).glob(f"bd-{key}-????????.jsonl"), reverse=True)


def export(cfg: ConfigDir, key: str, bd: Bd, now: float) -> str:
    """-> "" when today's export is there (made now or before), else why it could not be made."""
    target = backup_dir(cfg) / _name(key, now)
    if target.exists():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    try:
        code, out, err = bd(["export", "-o", str(temp)])
        counted = exported(out + err)
        if code or counted is None or not temp.is_file():
            return f"bd export exited {code}: {(err or out).strip()[-200:]}"
        target.with_suffix(".count").write_text(str(counted), encoding="utf-8")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    for old in exports(cfg, key)[KEEP:]:
        old.unlink()
        old.with_suffix(".count").unlink(missing_ok=True)
    return ""


def _drill_file(cfg: ConfigDir, key: str) -> Path:
    return backup_dir(cfg) / f"bd-{key}-drill.json"


def last_drill(cfg: ConfigDir, key: str) -> dict[str, object]:
    try:
        found = json.loads(_drill_file(cfg, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def check(path: Path, bd: Bd) -> str:
    """-> "" when the export reads back whole, else why not."""
    try:
        want = int(path.with_suffix(".count").read_text(encoding="utf-8"))
        lines = path.read_text(encoding="utf-8").splitlines()
        have = sum(1 for ln in lines if json.loads(ln).get("_type") == "issue")
    except (OSError, ValueError, AttributeError) as e:
        return f"{path.name} does not read back: {e}"
    if have != want:
        return f"{path.name} holds {have} issues, bd reported {want} when it was written"
    code, out, err = bd(["count"])
    live = out.strip()
    if code or not live.isdigit():
        return f"bd count exited {code}: {(err or out).strip()[-200:]}"
    return f"bd counts {live} issues now, fewer than the {want} exported in {path.name}" if int(live) < want else ""


def drill(cfg: ConfigDir, key: str, bd: Bd, now: float) -> str:
    """Once a UTC month: -> "" (not due, no export yet, or it passed) else why the newest export would not restore."""
    month = f"{datetime.fromtimestamp(now, UTC):%Y%m}"
    newest = exports(cfg, key)
    if last_drill(cfg, key).get("month") == month or not newest:
        return ""
    why = check(newest[0], bd)
    _drill_file(cfg, key).write_text(json.dumps({"month": month, "file": newest[0].name, "ok": not why, "why": why}), encoding="utf-8")
    return why


def nightly(cfg: ConfigDir, key: str, bd: Bd, now: float) -> list[str]:
    """The loop's chore: today's export, then this month's drill. -> what to say on the console (nothing when all is well)."""
    return [f"loop: bd backup: {why}" for why in (export(cfg, key, bd, now), drill(cfg, key, bd, now)) if why]
