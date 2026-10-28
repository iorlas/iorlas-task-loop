"""What a repo's loop is doing, as facts read from the stores, and the two texts made from them: `tl status --brief` (for a person,
or --json) and the handoff (for the next session). Never summarised by a model: every line is a field."""
import time
from dataclasses import asdict, dataclass

STATUS_LINES = 40
STATUS_BYTES = 8 * 1024
HANDOFF_BYTES = 4 * 1024

# The standing rules a fresh session must not have to rediscover (CLAUDE.md of this repo and the skill).
RULES = (
    "work in a worktree; never edit a plugin cache dir or the main checkout by hand",
    "release only through python3 dev/release.py; never bump a version by hand",
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
class Brief:
    repo: str
    now: float
    loops: tuple[LoopLine, ...] = ()
    last_beat: float = 0.0
    last_exit: str = ""
    asks: tuple[AskLine, ...] = ()
    slots: tuple[str, ...] = ()
    recent: tuple[str, ...] = ()
    version: str = ""
    installed: str = ""
    pinned: str = ""


def ago(now: float, t: float) -> str:
    if t <= 0:
        return "never"
    mins = max(0, int((now - t) // 60))
    return f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago" if mins < 48 * 60 else f"{mins // 1440} d ago"


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
    out.append(f"versions: running {b.version or '?'}, newest installed {b.installed or '?'}, pin {b.pinned or 'none'}")
    out.append(f"asks: {len(b.asks)} open")
    out += [f"  {a.bead} [{a.kind}] {a.decision[:90]} ({ago(b.now, a.since)})" for a in b.asks]
    if b.slots:
        out.append("slots:")
        out += [f"  {s}" for s in b.slots]
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
    return {"running": bool(b.loops), "summary": first_line(b), **asdict(b)}


def handoff_text(b: Brief) -> str:
    """The facts a session that lost its context needs, in at most 4 KB: the status line, the standing rules, then the rest (which is
    what gets cut when the text is too long)."""
    lines = [f"# task-loop handoff of {clock(b.now)}", "", first_line(b), "standing rules:", *[f"- {r}" for r in RULES], "", *body(b)]
    return "\n".join(clip(lines, 10_000, HANDOFF_BYTES)) + "\n"
