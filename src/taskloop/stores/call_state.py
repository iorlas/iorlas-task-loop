"""One vendor call in flight, on disk: the checkpoint that lets a killed loop, a sleeping laptop or a dropped network resume
the step instead of the run (tl-7y6.2.13; 60-design-A1 sec 2.3, `CallState` was `StepState`).

File: <dir>/<bead>.call.json, written by tmp + os.replace, one writer (the engine that owns the bead). Phases:
calling (written BEFORE the call) -> returned (the raw answer is on disk BEFORE it is validated) -> consumed (the node file
exists). `reattach` says what a restart does with it: use the finished answer (never discard output), resume the vendor
thread with a short note (never restart a thread that has a ref), or start the call.

"""

import contextlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

V = 1
NETWORK_RESUME_DELTA = "The connection dropped. Continue from where you stopped; your last output was cut. Do not restart."


@dataclass
class CallState:
    run: str
    bead: str
    key: tuple[object, ...]  # (step, stage, round, n): its own coordinates; another key on load discards the file
    phase: str = "calling"  # calling | returned | consumed
    lane: str = ""
    role: str = ""
    resume_of: str = ""  # the ref this call resumed, "" for a new thread
    ref: str = ""  # the vendor session id, "" until the vendor publishes it
    prompt_sha: str = ""
    t_call: float = 0.0
    t_ref: float = 0.0
    answer_file: str = ""  # set once `returned`
    v: int = V
    dir: str = field(default="", repr=False, compare=False)

    @property
    def path(self) -> Path:
        return path_for(self.dir, self.bead)

    def save(self) -> CallState:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        d = asdict(self)
        d.pop("dir")
        d["key"] = list(self.key)
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, p)
        return self

    def note_ref(self, ref: str, now: float = 0.0) -> CallState:
        """The vendor published its session id (the worker line on stderr); the first ref sticks."""
        if ref and not self.ref:
            self.ref, self.t_ref = ref, now
            self.save()
        return self

    def returned(self, answer: object, answer_file: str | Path, now: float = 0.0) -> CallState:
        """The raw answer goes to answer_file first, then the phase moves: a crash between them loses nothing."""
        af = Path(answer_file)
        af.parent.mkdir(parents=True, exist_ok=True)
        tmp = af.with_name(f"{af.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(answer), encoding="utf-8")
        os.replace(tmp, af)
        if not self.ref and isinstance(answer, dict):
            self.ref = str(answer.get("ref") or "")
        self.phase, self.answer_file = "returned", str(af)
        return self.save()

    def consumed(self) -> CallState:
        self.phase = "consumed"
        return self.save()

    def drop(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()


def path_for(dir_: str | Path, bead: str) -> Path:
    return Path(dir_) / (bead + ".call.json")


def begin(
    dir_: str | Path,
    run: str,
    bead: str,
    key: Sequence[object],
    role: str = "",
    lane: str = "",
    resume_of: str = "",
    prompt_sha: str = "",
    now: float = 0.0,
) -> CallState:
    """phase=calling, on disk before the vendor is called."""
    return CallState(run, bead, tuple(key), "calling", lane, role, resume_of, resume_of, prompt_sha, now, 0.0, "", V, str(dir_)).save()


def load_for(dir_: str | Path, bead: str, key: Sequence[object]) -> CallState | None:
    """The bead's CallState when it is for this key, else None: no file, damaged, a newer version, another key."""
    try:
        d = json.loads(path_for(dir_, bead).read_text(encoding="utf-8"))
        if int(d.get("v", 0)) > V or tuple(d.get("key") or ()) != tuple(key):
            return None
        known = {f.name for f in fields(CallState)} - {"dir"}
        d = {k: v for k, v in d.items() if k in known}
        d["key"] = tuple(d["key"])
        return CallState(dir=str(dir_), **d)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def reattach(st: CallState | None) -> tuple[Any, ...] | None:
    """What a start does with the file: ("answer", dict) a returned answer that still reads; ("resume", ref, note) a call
    that had a session; None to call as usual (no state, consumed, or a call that never got a ref)."""
    if st is None:
        return None
    if st.phase == "returned" and st.answer_file:
        try:
            a = json.loads(Path(st.answer_file).read_text(encoding="utf-8"))
            if isinstance(a, dict):
                return ("answer", a)
        except (OSError, ValueError):
            pass
    if st.phase in ("calling", "returned") and st.ref:
        return ("resume", st.ref, NETWORK_RESUME_DELTA)
    return None
