"""What a repo's loop is doing, as facts read from the stores, and the two texts made from them: `tl status --brief` (for a person,
or --json) and the handoff (for the next session). Never summarised by a model: every line is a field."""
import time
from dataclasses import asdict, dataclass
from typing import Final

from taskloop.domain import versions
from tlkernel.ago import ago

STATUS_LINES: Final = 40
STATUS_BYTES: Final = 8 * 1024
HANDOFF_BYTES: Final = 4 * 1024

# The standing rules a fresh session must not have to rediscover (CLAUDE.md of this repo and the skill).
RULES: Final = (
    "work in a worktree; never edit a plugin cache dir or the main checkout by hand",
    "release only through uv run --script dev/release.py; never bump a version by hand",
    "never pkill/killall or kill by pattern: only a PID you confirmed is yours",
    "a human decision is relayed with the quoted words and a timestamp; an empty approval is refused for an override",
    "fork a session only for read-only work of 4 h or less; otherwise start fresh with a written brief",
    "every bd call goes through tl (the actor), prose in a bead comment never acts",
)


@dataclass(frozen=True)
class LoopLine:
    pid: int
    since: float
    bead: str
    slot: str
    version: str


@dataclass(frozen=True)
class AskLine:
    bead: str
    kind: str
    decision: str
    since: float


@dataclass(frozen=True)
class ResourceLine:
    """One held unit of an engine.resources lease: who holds it (bead and check, from the holder's label) and since when."""

    name: str
    bead: str
    check: str
    since: float


@dataclass(frozen=True)
class Brief:
    repo: str
    now: float
    loops: tuple[LoopLine, ...] = ()
    last_beat: float = 0.0
    last_exit: str = ""
    asks: tuple[AskLine, ...] = ()
    slots: tuple[str, ...] = ()
    resources: tuple[ResourceLine, ...] = ()
    recent: tuple[str, ...] = ()
    version: str = ""
    installed: str = ""
    pinned: str = ""
    shim_sha256: str = ""


def clock(t: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(t))


def first_line(b: Brief) -> str:
    """Loop RUNNING or NOT RUNNING, and when it last did anything."""
    if b.loops:
        return f"loop RUNNING ({len(b.loops)}) on {b.repo}, last activity {ago(b.now, b.last_beat)}"
    return f"loop NOT RUNNING on {b.repo}, last activity {ago(b.now, b.last_beat)}" + (f" (exit: {b.last_exit})" if b.last_exit else "")


def body(b: Brief) -> list[str]:
    out: list[str] = []
    for lp in b.loops:
        now = f"{lp.bead} in {lp.slot or 'its worktree'}" if lp.bead else "between beads"
        out.append(f"  pid {lp.pid} since {clock(lp.since)}: {now}; task-loop {lp.version}")
    out.append(f"versions: running {b.version or '?'}, newest installed {b.installed or '?'}, pin {b.pinned or 'none'}"
               + (f", shim {b.shim_sha256[:8]}" if b.shim_sha256 else ""))
    odd = versions.skew([lp.version for lp in b.loops], b.installed)
    if odd:
        out.append(f"SKEW: loop engine(s) on {', '.join(odd)}, newest installed {b.installed}")
    out.append(f"asks: {len(b.asks)} open")
    out += [f"  {a.bead} [{a.kind}] {a.decision[:90]} ({ago(b.now, a.since)})" for a in b.asks]
    if b.slots:
        out.append("slots:")
        out += [f"  {s}" for s in b.slots]
    if b.resources:
        out.append("resources held:")
        out += [f"  {r.name}: {r.bead} {r.check} held {max(0, int(b.now - r.since))} s" for r in b.resources]
    if b.recent:
        out.append("recent beads:")
        out += [f"  {r}" for r in b.recent]
    return out


def fits(lines: list[str], max_lines: int, max_bytes: int) -> bool:
    return len(lines) <= max_lines and sum(len(ln.encode()) + 1 for ln in lines) <= max_bytes


def clip(lines: list[str], max_lines: int, max_bytes: int) -> list[str]:
    """The lines as they are when they fit, else the first ones that leave room for a last line saying how many were left out."""
    if fits(lines, max_lines, max_bytes):
        return lines
    kept: list[str] = []
    size = 0
    for ln in lines:
        n = len(ln.encode()) + 1
        if len(kept) >= max_lines - 1 or size + n > max_bytes - 40:
            break
        kept.append(ln)
        size += n
    return [*kept, f"... {len(lines) - len(kept)} more line(s)"]


def status_lines(b: Brief) -> list[str]:
    return clip([first_line(b), *body(b)], STATUS_LINES, STATUS_BYTES)


def status_json(b: Brief) -> dict[str, object]:
    loops = [lp.version for lp in b.loops]
    census = {"running": b.version, "installed": b.installed, "pinned": b.pinned, "loops": loops, "shim_sha256": b.shim_sha256,
              "skew": versions.skew(loops, b.installed)}
    return {"running": bool(b.loops), "summary": first_line(b), **asdict(b), "versions": census}


def handoff_text(b: Brief) -> str:
    """The facts a session that lost its context needs, in at most 4 KB: the status line, the standing rules, then the rest (which is
    what gets cut when the text is too long)."""
    lines = [f"# task-loop handoff of {clock(b.now)}", "", first_line(b), "standing rules:", *[f"- {r}" for r in RULES], "", *body(b)]
    return "\n".join(clip(lines, 10_000, HANDOFF_BYTES)) + "\n"
