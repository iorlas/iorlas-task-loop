"""Where a run's files live (contracts/locator.py finds them, its manifest is the authority): its engine log and stderr,
its run folder outside the worktree (brief, plan, node answers, check results,
where no worker can write them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners), and
the writer's scratch folder in the worktree."""
import contextlib
import os
import shutil
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import locks
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import TASK_EXCLUDE, ConfigDir
from taskloop.contracts.ports import Git


def newest_write(path: Path) -> float:
    """When anything in `path` (a file, or a folder and all it holds) was last written."""
    latest = 0.0
    for dirpath, _, names in os.walk(path):
        for n in [".", *names]:
            with contextlib.suppress(OSError):
                latest = max(latest, os.stat(os.path.join(dirpath, n)).st_mtime)
    return latest


def prune_check_rounds(cfg: ConfigDir, days: float, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """Every round's check log (NN-id.rK.log) of a run older than `days` goes; plans, briefs and evidence stay. A bead in `exempt`
    keeps its logs. -> what went (what would, with `dry_run`)."""
    cut = time.time() - days * 86400
    gone: list[Path] = []
    for b in RunLocator(cfg).runs():
        if b.bead in exempt:
            continue
        for f in b.dir.glob("checks/*.r*.log"):
            stem, _, ext = f.name.rpartition(".")
            _, _, round_ = stem.rpartition(".r")
            try:
                if ext == "log" and round_.isdigit() and f.stat().st_mtime < cut:
                    gone.append(f)
                    if not dry_run:
                        f.unlink()
            except OSError:
                pass
    return gone


def prune_run_dirs(cfg: ConfigDir, days: float, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """A run folder (brief, plan, answers, check results, evidence, looks) nothing wrote to for `days` goes whole, unless its bead
    is in `exempt`. A folder with no manifest is no run: it stays. -> what went (what would, with `dry_run`)."""
    cut = time.time() - days * 86400
    gone = [b.dir for b in RunLocator(cfg).runs() if b.bead not in exempt and newest_write(b.dir) < cut]
    for d in gone if not dry_run else []:
        shutil.rmtree(d, ignore_errors=True)
    return gone


def prune_run_logs(cfg: ConfigDir, now: float, retain: float, exempt: Collection[str] = (), dry_run: bool = False) -> list[Path]:
    """An engine log not written for `retain` seconds goes with its .live/ folder (the worker's per-call files), its .stderr and an
    owner's request left in its run folder; the log of a bead in `exempt` stays. The dashboard only reads: `tl prune` (the loop runs it
    at its start) is the one place that deletes them. A live run beats every minute and is never old.
    -> the logs that went (would, with `dry_run`)."""
    gone: list[Path] = []
    for b in RunLocator(cfg).runs():
        with contextlib.suppress(OSError):
            if not b.log.exists() or b.log.stat().st_mtime >= now - retain or b.bead in exempt:
                continue
            gone.append(b.log)
            if dry_run:
                continue
            drop_run_log(cfg, b)
    return gone


def drop_run_log(cfg: ConfigDir, b: RunBundle) -> None:
    """One engine log with its .live/ folder, .stderr and an owner's request no run took (the run's close drops it too)."""
    shutil.rmtree(b.live, ignore_errors=True)
    b.err.unlink(missing_ok=True)
    cfg.run_request(b.run).unlink(missing_ok=True)
    cfg.run_request_lock(b.run).unlink(missing_ok=True)
    locks.holder_file(cfg.run_request_lock(b.run)).unlink(missing_ok=True)
    b.log.unlink()


def repo_of(git: Git, wt: str | Path) -> str:
    """The repo's path as asks and decisions name it: the parent of the git common dir (the worktree when git cannot say)."""
    common = git.common_dir(str(wt))
    return str(Path(common).parent) if common else str(wt)


@dataclass(frozen=True)
class RunLayout:
    run: str  # the run id
    log_path: Path
    err_path: Path
    live_dir: Path  # the worker's per-call files
    run_dir: Path
    task_dir: Path  # the writer's: only evidence/ lives here
    brief_file: Path  # the brief as the writer can re-read it: the engine's copy stays in run_dir
    evidence_dir: Path  # the writer's proof of what the engine cannot rerun

    @classmethod
    def open(cls, bead: str, wt: str | Path, taken: str | None, home: ConfigDir, repo: str, now: float,
             loop: str | None = None) -> RunLayout:
        """The layout of the run `taken` (a run that goes on after an exec or a pause), else of a new one; its folders are made and its
        manifest is written (a new run) or counts one more attempt (a run taken up)."""
        where = RunLocator(home)
        b = where.take_up(taken, repo, bead, now) if taken else where.create(repo, bead, now, loop)
        task_dir = Path(wt) / TASK_EXCLUDE.rstrip("/") / bead
        task_dir.mkdir(parents=True, exist_ok=True)
        evidence = task_dir / "evidence"
        evidence.mkdir(exist_ok=True)
        return cls(b.run, b.log, b.err, b.live, b.dir, task_dir, task_dir / "brief.md", evidence)
