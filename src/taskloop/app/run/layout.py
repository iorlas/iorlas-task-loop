"""Where a run's files live: its engine log and stderr, its run folder outside the worktree (brief, plan, node answers, check results,
where no worker can write them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners), and
the writer's scratch folder in the worktree."""
import contextlib
import os
import shutil
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import ident, locks
from taskloop.contracts.paths import TASK_EXCLUDE, ConfigDir
from taskloop.contracts.runlife import RETAIN

CHECK_ROUNDS_DAYS = 14


def bead_of(stem: str) -> str:
    """The bead of a run id (<bead>-YYYYMMDD-HHMMSS)."""
    return stem.rsplit("-", 2)[0]


def newest_write(path: Path) -> float:
    """When anything in `path` (a file, or a folder and all it holds) was last written."""
    latest = 0.0
    for dirpath, _, names in os.walk(path):
        for n in [".", *names]:
            with contextlib.suppress(OSError):
                latest = max(latest, os.stat(os.path.join(dirpath, n)).st_mtime)
    return latest


def prune_check_rounds(runs: Path, days: float = CHECK_ROUNDS_DAYS, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """Every round's check log (NN-id.rK.log) of a run older than `days` goes; plans, briefs and evidence stay. A bead in `exempt`
    keeps its logs. -> what went (what would, with `dry_run`)."""
    cut = time.time() - days * 86400
    gone: list[Path] = []
    for f in runs.glob("*/checks/*.r*.log"):
        stem, _, ext = f.name.rpartition(".")
        _, _, round_ = stem.rpartition(".r")
        try:
            if ext == "log" and round_.isdigit() and f.stat().st_mtime < cut and bead_of(f.parent.parent.name) not in exempt:
                gone.append(f)
                if not dry_run:
                    f.unlink()
        except OSError:
            pass
    return gone


def prune_run_dirs(runs: Path, days: float, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """A run folder (brief, plan, answers, check results, evidence, looks) nothing wrote to for `days` goes whole, unless its bead
    is in `exempt`. -> what went (what would, with `dry_run`)."""
    cut = time.time() - days * 86400
    gone = [d for d in sorted(runs.glob("*")) if d.is_dir() and bead_of(d.name) not in exempt and newest_write(d) < cut]
    for d in gone if not dry_run else []:
        shutil.rmtree(d, ignore_errors=True)
    return gone


def prune_run_logs(cfg: ConfigDir, now: float, retain: float = RETAIN, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """An engine log not written for `retain` seconds goes with its .live/ folder (the worker's per-call files), its .stderr and an
    owner's request left in its run folder; the log of a bead in `exempt` stays. The dashboard only reads: this, at each run's start,
    is the one place that deletes them. A live run beats every minute and is never old. -> the logs that went (would, with `dry_run`)."""
    gone: list[Path] = []
    for log in cfg.engine_log("*").parent.glob("*.jsonl"):
        with contextlib.suppress(OSError):
            if log.stat().st_mtime >= now - retain or bead_of(log.stem) in exempt:
                continue
            gone.append(log)
            if dry_run:
                continue
            shutil.rmtree(cfg.live_dir(log.stem), ignore_errors=True)
            log.with_suffix(".stderr").unlink(missing_ok=True)
            cfg.run_request(log.stem).unlink(missing_ok=True)  # an owner's request no run took (the run's close drops it too)
            cfg.run_request_lock(log.stem).unlink(missing_ok=True)
            locks.holder_file(cfg.run_request_lock(log.stem)).unlink(missing_ok=True)
            log.unlink()
    return gone


def fresh_stem(bead: str, logs: Path) -> str:
    """A fresh run has its own id, also when the last run of this bead began in the same second: the stamp moves on."""
    t0, n = time.time(), 0
    while True:
        stem = f"{bead}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(t0 + n))}"
        if not ((logs / f"{stem}.jsonl").exists() or (ident.config_dir() / "runs" / stem).exists()):
            return stem
        n += 1


@dataclass(frozen=True)
class RunLayout:
    log_path: Path
    err_path: Path
    run_dir: Path
    task_dir: Path  # the writer's: only evidence/ lives here
    brief_file: Path  # the brief as the writer can re-read it: the engine's copy stays in run_dir
    evidence_dir: Path  # the writer's proof of what the engine cannot rerun

    @classmethod
    def open(cls, bead: str, wt: str | Path, taken: str | None) -> "RunLayout":
        """The layout of the run `taken` (a run that goes on after an exec or a pause), else of a new one; its folders are made."""
        logs = ident.config_dir() / "engine"
        logs.mkdir(exist_ok=True)
        stem = taken or fresh_stem(bead, logs)
        run_dir = ident.config_dir() / "runs" / stem
        run_dir.mkdir(parents=True, exist_ok=True)
        prune_check_rounds(ident.config_dir() / "runs")
        prune_run_logs(ConfigDir(ident.config_dir()), time.time())
        task_dir = Path(wt) / TASK_EXCLUDE.rstrip("/") / bead
        task_dir.mkdir(parents=True, exist_ok=True)
        evidence = task_dir / "evidence"
        evidence.mkdir(exist_ok=True)
        return cls(logs / f"{stem}.jsonl", logs / f"{stem}.stderr", run_dir, task_dir, task_dir / "brief.md", evidence)
