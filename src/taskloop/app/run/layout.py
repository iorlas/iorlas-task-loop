"""Where a run's files live: its engine log and stderr, its run folder outside the worktree (brief, plan, node answers, check results,
where no worker can write them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners), and
the writer's scratch folder in the worktree."""
import time
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import ident
from taskloop.contracts.paths import TASK_EXCLUDE

CHECK_ROUNDS_DAYS = 14


def prune_check_rounds(runs: Path, days: int = CHECK_ROUNDS_DAYS) -> None:
    """Every round's check log (NN-id.rK.log) of a run older than `days` goes; plans, briefs and evidence stay."""
    cut = time.time() - days * 86400
    for f in runs.glob("*/checks/*.r*.log"):
        stem, _, ext = f.name.rpartition(".")
        _, _, round_ = stem.rpartition(".r")
        try:
            if ext == "log" and round_.isdigit() and f.stat().st_mtime < cut:
                f.unlink()
        except OSError:
            pass


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
        task_dir = Path(wt) / TASK_EXCLUDE.rstrip("/") / bead
        task_dir.mkdir(parents=True, exist_ok=True)
        evidence = task_dir / "evidence"
        evidence.mkdir(exist_ok=True)
        return cls(logs / f"{stem}.jsonl", logs / f"{stem}.stderr", run_dir, task_dir, task_dir / "brief.md", evidence)
