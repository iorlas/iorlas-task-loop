"""Run planned runs with N in flight. One run = `tl rounds start --exit-when-idle` to its own end (no polling, no pid, no
signal from here); a wall cap stops that process tree through the process library. Then collect the verdict and evidence."""

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from exp_arms import Builder, Paths, Proc, SetupFailed, tl_argv, tool_env
from exp_spec import Outcome, Run, RunResult, Spec

READ_SECONDS = 120.0


def load_average() -> list[str]:
    try:
        return Path("/proc/loadavg").read_text().split()[:3]
    except OSError:
        return []  # not Linux: unknown, never zero


class Runner:
    def __init__(self, spec: Spec, proc: Proc, clock: Callable[[], float] = time.time) -> None:
        self.spec, self.proc, self.clock = spec, proc, clock
        self.builder = Builder(spec, proc)

    def tl(self, paths: Paths, *args: str) -> str:
        done = self.proc(tl_argv(self.spec, paths, *args), cwd=self.spec.engine, env=tool_env(self.spec), timeout=READ_SECONDS)
        return done.out.decode(errors="replace") if done.exit == 0 else ""

    def one(self, run: Run, in_flight: int) -> RunResult:
        paths = Paths(self.spec, run)
        result = RunResult(run=run, outcome=Outcome.INFRA, started=self.clock(), in_flight_planned=in_flight, load_start=load_average())
        try:
            result.arm_base = self.builder.arm(run)
            result.outcome, result.detail = self.rounds(run, paths)
        except SetupFailed as error:
            result.detail = str(error)
        result.ended, result.load_end = self.clock(), load_average()
        if result.arm_base and paths.db.exists():
            result.export = self.export(paths)
            result.diffstat, result.patch = self.diff(run, paths, result.arm_base)
            if result.outcome is Outcome.INCOMPLETE:
                result.outcome = self.verdict(paths)
        return result

    def rounds(self, run: Run, paths: Paths) -> tuple[Outcome, str]:
        spec = self.spec
        argv = tl_argv(
            spec, paths, "rounds", "start", "--no-dashboard", "--exit-when-idle", "--round-seconds", str(spec.round_seconds),
            "--backlog", spec.backlog, "--tracker-root", str(paths.tracker), "--checkout", str(paths.repo), "--label", spec.label,
            "--max-running", "1", "--minutes", str(spec.attempt_minutes), "--db", str(paths.db), "--artifacts", str(paths.artifacts),
            "--workflow", spec.arms[run.arm].workflow,
        )  # fmt: skip
        done = self.proc(argv, cwd=spec.engine, env=tool_env(spec), timeout=spec.wall_minutes * 60.0)
        (paths.root / "rounds.out").write_bytes(done.out + done.err)
        if done.timed_out:
            return Outcome.CAP_WALL, "the rounds' process tree was stopped at the wall cap"
        if done.exit:
            return Outcome.INFRA, f"rounds exit={done.exit}: {done.err.decode(errors='replace')[-300:]}"
        return Outcome.INCOMPLETE, ""  # ended idle; `verdict` reads the state

    def verdict(self, paths: Paths) -> Outcome:
        """From the attempt rows (state), never from logs: the last row waiting to be landed passed; a hold held."""
        try:
            rows = json.loads(self.tl(paths, "attempt", "list", "--db", str(paths.db), "--json"))["attempts"]
        except ValueError, KeyError:
            return Outcome.INCOMPLETE
        last = rows[-1] if rows else {}
        return Outcome.PASS if last.get("status") == "waiting_for_land" else Outcome.HELD if last.get("hold") else Outcome.INCOMPLETE

    def export(self, paths: Paths) -> list[dict[str, object]]:
        try:
            rows = json.loads(self.tl(paths, "attempt", "export", "--db", str(paths.db), "--json"))
        except ValueError:
            return []
        return rows if isinstance(rows, list) else []

    def diff(self, run: Run, paths: Paths, arm_base: str) -> tuple[str, str]:
        """The run's `task/<id>` branch in the local origin against the arm's base: numstat and the patch file."""
        git = ["git", "-C", str(paths.repo)]
        branch = f"origin/task/{run.task}"
        self.proc([*git, "fetch", "-q", "origin"], cwd=None, env=tool_env(self.spec), timeout=READ_SECONDS)
        stat = self.proc([*git, "diff", "--numstat", arm_base, branch], cwd=None, env=tool_env(self.spec), timeout=READ_SECONDS)
        patch = self.proc([*git, "diff", arm_base, branch], cwd=None, env=tool_env(self.spec), timeout=READ_SECONDS)
        target = self.spec.work / "diffs" / f"{run.name}.patch"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patch.out if patch.exit == 0 else b"")
        return (stat.out.decode(errors="replace") if stat.exit == 0 else ""), str(target)

    def all(self, runs: list[Run]) -> list[RunResult]:
        """The plan's runs in order, `in_flight` at a time, each result saved as it ends (`results/<run>.json`)."""
        self.builder.shared()
        folder = self.spec.work / "results"
        folder.mkdir(parents=True, exist_ok=True)

        def go(run: Run) -> RunResult:
            found = self.one(run, self.spec.in_flight)
            (folder / f"{run.name}.json").write_text(found.model_dump_json(indent=1))
            return found

        with ThreadPoolExecutor(self.spec.in_flight) as pool:
            return list(pool.map(go, runs))
