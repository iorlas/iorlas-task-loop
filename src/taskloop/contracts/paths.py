"""Every file location, once. Nothing else in the package names a file or a folder of ours."""
import os
from pathlib import Path

from taskloop.contracts.ids import BeadId, RunId


def default_root() -> Path:
    """~/.config/task-loop, or $XDG_CONFIG_HOME/task-loop. Not created here."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "task-loop"


class ConfigDir:
    """The per-user state folder."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def engine_log(self, run: RunId | str) -> Path:
        return self.root / "engine" / ("%s.jsonl" % run)

    def live_dir(self, run: RunId | str) -> Path:
        return self.root / "engine" / ("%s.live" % run)

    def events(self) -> Path:
        return self.root / "events.jsonl"

    def traces(self) -> Path:
        return self.root / "traces.jsonl"

    def ask(self, bead: BeadId | str) -> Path:
        return self.root / "asks" / ("%s.json" % bead)

    def asks_dir(self) -> Path:
        return self.root / "asks"

    def ask_beads(self) -> list[str]:
        """The beads that have an ask file, sorted."""
        try:
            return sorted(p.stem for p in self.asks_dir().glob("*.json"))
        except OSError:
            return []

    def ask_marker(self, sweep: str) -> Path:
        """When a throttled sweep of the asks last ran (the file's mtime); not an ask, so the store never lists it."""
        return self.root / "asks" / ("." + sweep)

    def checkpoint(self, bead: BeadId | str) -> Path:
        return self.root / "checkpoints" / ("%s.json" % bead)

    def run_dir(self, run: RunId | str) -> Path:
        return self.root / "runs" / str(run)

    def check_run(self, run: RunId | str, rnd: int | None = None) -> Path:
        """The CheckRun of a round of the run; no round: the latest."""
        return self.run_dir(run) / ("engine-checks.json" if rnd is None else "engine-checks.r%d.json" % rnd)

    def check_logs(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "checks"

    def check_cache(self, bead: BeadId | str) -> Path:
        return self.root / "check-cache" / ("%s.json" % bead)

    def check_durations(self, repo_key: str) -> Path:
        return self.root / "check-durations" / ("%s.json" % repo_key)

    def loop_state(self, repo_key: str) -> Path:
        return self.root / "loop" / ("%s.json" % repo_key)

    def loop_command(self, repo_key: str) -> Path:
        return self.root / "loop" / ("%s.command.json" % repo_key)

    def loop_log(self, repo_key: str) -> Path:
        return self.root / "loop" / ("%s.jsonl" % repo_key)

    def loop_runs(self, repo_key: str) -> Path:
        """The loop's own folder of the repo: run logs, outcome files, loop-<pid>.log, exits.jsonl, died-<pid>.json."""
        return self.root / "loop" / repo_key

    def loop_rest(self, repo_key: str) -> Path:
        return self.root / "loop" / ("%s-rest.json" % repo_key)

    def ticket(self, repo_key: str, seq: int) -> Path:
        return self.root / "slots" / repo_key / ("%06d.json" % seq)

    def ticket_counter(self, repo_key: str) -> Path:
        return self.root / "slots" / repo_key / "seq"

    def slot_setup_mark(self, key: str) -> Path:
        return self.root / "slots" / ("%s.setup" % key)

    def lock_record(self, what: str, ident: str) -> Path:
        return self.root / "locks" / ("%s-%s.lock" % (what, ident))

    def snapshot(self, repo_key: str, name: str) -> Path:
        return self.root / "snapshots" / ("%s.%s.json" % (repo_key, name))

    def session(self, session_id: str) -> Path:
        return self.root / "sessions" / ("%s.json" % session_id)

    def repos(self) -> Path:
        return self.root / "repos.json"

    def shared(self, repo_key: str) -> Path:
        return self.root / "shared" / ("%s.json" % repo_key)

    def pin(self) -> Path:
        return self.root / "pinned.json"

    def bad_versions(self) -> Path:
        return self.root / "bad-versions.json"

    def release_result(self) -> Path:
        return self.root / "releases" / "last.json"

    def reflect_view(self) -> Path:
        return self.root / "reflect-view.json"

    def dash_state(self) -> Path:
        return self.root / "dash.json"


TASK_EXCLUDE = ".task/"  # the line a repo's info/exclude carries so the scratch folder is never committed


class RepoDirs:
    """The scratch folder a worktree carries (.task/, never committed)."""

    def __init__(self, worktree: Path | str) -> None:
        self.worktree = Path(worktree)
        self.task = self.worktree / ".task"

    def engine_lock(self) -> Path:
        return self.task / "engine.lock"

    def check_log(self, name: str) -> Path:
        return self.task / "checks" / name
