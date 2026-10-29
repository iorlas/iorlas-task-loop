"""The loop process itself: its log, its state file, its stop and its nap. The pass logic is in loop.py."""
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles, StopMode
from taskloop.app.loop.gate import GateRole
from taskloop.app.loop.net import NetState
from taskloop.app.loop.settle import Counters
from taskloop.contracts.config import LoopConfig, RepoProfile
from taskloop.contracts.loop import Carry, LoopState, QueueRow


@dataclass(frozen=True)
class Running:
    bead: str
    slot: str
    since: float
    child: int
    run_log: str
    worktree: str = ""


class Core:
    def __init__(self, env: LoopEnv, files: LoopFiles, inherited: LoopState | None) -> None:
        self.env, self.files = env, files
        self.prof: RepoProfile = env.profile()
        self.started = inherited.started if inherited else env.now()
        carry = inherited.carry if inherited else Carry()
        self.carry_in = carry
        self.c = Counters(fails=list(carry.fails), ran=carry.ran, later=dict(carry.later), pauses=dict(carry.pauses),
                          warned=list(carry.warned))
        self.sigterm = threading.Event()  # SIGTERM or Ctrl-C to the loop itself: end the running bead as `tl stop --now` does
        self.gate = GateRole(env.roles, env.now, self.tune().gate_cache, self.tune().gate_unknown)
        self.gate.held = {k: (v[0], v[1]) for k, v in carry.gated.items()}
        self.net = NetState(self.tune().net_probe)
        self.log: Path | None = None
        self.rows: list[QueueRow] = []
        self.first_seen: dict[str, float] = {}
        self.exit: dict[str, str] = {}
        self.beat_at = 0.0
        self.now_running: Running | None = None
        self.until = carry.until
        self.wt = carry.wt
        self.st = LoopState(pid=env.pid, started=self.started, t=env.now(), repo=env.repo, version=env.version, code_dir=env.code_dir,
                            actor=env.actor())

    def tune(self) -> LoopConfig:
        return self.prof.loop

    # ---- log -----------------------------------------------------------------------------------------------------
    def say(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S', time.localtime(self.env.now()))}] loop: {text}"
        self.env.say(line)
        if self.log:
            try:
                with open(self.log, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def open_log(self) -> Path:
        """loop-<pid>.log under the repo's loop folder (the newest `logs_kept` stay); its path is shown by `tl loop status`."""
        d = self.files.runs()
        self.log = d / f"loop-{self.env.pid}.log"
        old = sorted((f for f in d.glob("loop-*.log") if f != self.log), key=lambda f: f.stat().st_mtime)
        for f in old[:max(0, len(old) - (self.tune().logs_kept - 1))]:
            f.unlink(missing_ok=True)
        return self.log

    # ---- the state file ----------------------------------------------------------------------------------------
    def carry(self) -> Carry:
        c = self.c
        return Carry(fails=list(c.fails), ran=c.ran, later=dict(c.later), pauses=dict(c.pauses),
                     gated=dict(self.gate.held), warned=list(c.warned), until=self.until, wt=self.wt, back=self.carry_in.back,
                     moved_at=self.carry_in.moved_at, fallback=self.carry_in.fallback)

    def running(self, now: Running | None) -> None:
        """The bead that runs now (None: none) and where; rewrites the state file."""
        self.now_running = now
        self.publish()

    def publish(self) -> None:
        """Rewrite the state file: every write is a sign of life (`t`), and carries the queue and the stop it has seen."""
        mode = self.stop_mode()
        stop = LoopFiles.stop_request(mode, "tl", self.env.now()) if mode else None
        r = self.now_running
        self.st = self.st.model_copy(update={
            "t": self.env.now(), "queue": self.rows, "carry": self.carry(), "stop": stop, "log": str(self.log or ""),
            "worktree": r.worktree if r else self.wt, "bead": r.bead if r else None, "slot": r.slot if r else None,
            "since": r.since if r else None, "child": r.child if r else None, "run_log": r.run_log if r else ""})
        self.beat_at = self.env.now()
        self.files.write(self.st)

    def beat(self) -> None:
        """The loop is alive: stamp the state file, at most every `beat_every` s."""
        if self.env.now() - self.beat_at >= self.tune().beat_every:
            self.publish()

    # ---- stop and sleep -------------------------------------------------------------------------------------
    def stop_mode(self) -> StopMode:
        """'now', 'after' (stop after the current bead) or '' (go on)."""
        return "now" if self.sigterm.is_set() else self.files.stop_for(self.env.pid)

    def nap(self, secs: float, until: float = 0) -> None:
        """Sleep, waking early for a stop or the end time."""
        end = self.env.now() + secs
        while self.env.now() < end and not self.stop_mode() and not (until and self.env.now() >= until):
            self.beat()
            self.env.sleep(min(self.tune().poll, max(0.05, end - self.env.now())))

    def left(self, reason: str, detail: str = "") -> None:
        self.exit.update(reason=reason, detail=detail)

    def write_exit(self) -> None:
        """A loop that exits writes its reason to the repo's exits file and its event log; `tl loop status` shows the last one.
        A loop that cannot (SIGKILL) leaves died-<pid>.json."""
        reason = self.exit.get("reason") or ("signal" if self.sigterm.is_set() else "crash")
        detail = self.exit.get("detail", "")
        self.files.write_exit({"v": 1, "pid": self.env.pid, "repo": self.env.repo, "t": self.env.now(), "started": self.started,
                               "reason": reason, "detail": detail, "log_path": str(self.log or "")})
        self.env.event("loop_exit", who="loop", repo=self.env.repo, pid=self.env.pid, reason=reason, detail=detail[:200])


def prio_of(bead: object, default: int = 2) -> int:
    p = getattr(bead, "priority", None)
    return p if isinstance(p, int) else default
