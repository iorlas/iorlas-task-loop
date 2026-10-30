"""Dashboard fixtures: the round-8b mock data (tests/fixtures/dash/mock-8b.json) turned into contract records.

The same JSON is the frontend's dev data (dev/dash_fixtures.py serves it) and the backend's target shape. `python3
tests/support/dash_fixtures.py` rewrites tests/fixtures/dash/; tests/contracts/test_dash.py fails when the files drift from
this builder or stop decoding. Minutes in the mock are relative to now; NOW is fixed so the files are stable.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from taskloop.contracts import dash as D
from taskloop.contracts import dashcost as DC
from taskloop.contracts import wire
from taskloop.contracts.ids import BeadId
from taskloop.contracts.needs import NeedRow

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "tests" / "fixtures" / "dash"
NOW = 1793050200.0
TOKENS_PER_MIN = 9500
USUAL, USUAL_N = 600_000, 12

SlotState = Literal["free", "held", "idle", "look", "running", "stuck"]
TermTone = Literal["", "dim", "err", "ok"]
LiveState = Literal["crashed", "ended", "live"]
AskStatus = Literal["answered", "open", "open_soft"]
LaneState = Literal["locked", "ok", "stale", "watch"]

COLUMN = {"backlog": D.Column.BACKLOG, "working": D.Column.WORKING, "ask": D.Column.QUESTIONS, "review": D.Column.REVIEW,
          "look": D.Column.LOOK, "land": D.Column.LANDING, "done": D.Column.DONE}
KIND: dict[str, D.SegKind] = {"": "stage", "f": "failed", "live": "live", "park": "ask",
        "parkx": "answered", "wait": "look", "stuck": "stuck",
        "proj": "projected", "gap": "wait_slot"}
EPICS = {"Save system": "lifesim-d5f", "World": "lifesim-wld", "Economy": "lifesim-eco", "Dashboard v2": "tl-bcd",
         "Substrate": "tl-7y6"}
CAUSE = {"requirement gap": D.OwnerCause.REQUIREMENT, "decision": D.OwnerCause.DECISION, "environment": D.OwnerCause.ENVIRONMENT,
         "process": D.OwnerCause.PROCESS, "?": D.OwnerCause.UNKNOWN}
STAGES = list(D.Phase)


def full(project: str, bead: str) -> str:
    """The real bd id: <project>-<id>; ids that already carry the prefix (task-loop's `tl-`) stay."""
    return bead if bead.startswith(("tl-", project + "-")) else f"{project}-{bead}"


def L(bead: str) -> str:
    return full("lifesim", bead)


def at(minutes: float) -> float:
    return NOW + minutes * 60


def ago(text: str) -> float:
    """'6m', '1h', '-12m' (U+2212 minus also accepted), 'now' -> a time."""
    t = text.replace("\u2212", "").strip()
    if t == "now":
        return NOW
    n = float(t[:-1])
    return NOW - (n * 3600 if t.endswith("h") else n * 60)


def md(html: str) -> str:
    return re.sub(r"</?code>", "`", re.sub(r"<span[^>]*>|</span>", "", html))


def stage_of(label: str) -> D.Phase | None:
    if label == "your look":
        return D.Phase.LOOK
    if label.startswith("🛑"):
        return D.Phase.WRITE
    for s in STAGES:
        if label.startswith(s.value):
            return s
    return None


def work(b: dict) -> list:
    return [s for s in b.get("seg", []) if (s[3] if len(s) > 3 else "") != "proj"]


def kind(s: list) -> str:
    return s[3] if len(s) > 3 else ""


def marker(b: dict, by: dict) -> D.Marker:
    if b["col"] == "done":
        return D.Marker.DONE
    if b.get("bad"):
        return D.Marker.STUCK
    if b["col"] == "ask":
        return D.Marker.SOFT_ASK if b.get("soft") else D.Marker.ASK
    if b["col"] == "look":
        return D.Marker.LOOK
    if b["col"] == "backlog":
        return D.Marker.BLOCKED if any(n in by and by[n]["col"] != "done" for n in b.get("needs", [])) else D.Marker.READY
    return D.Marker.RUN


def dots(b: dict) -> list[D.PhaseDot]:
    w = work(b)
    if not w:
        return []
    seen = {stage_of(s[0]) for s in w}
    last = w[-1]
    cur = stage_of(last[0])
    out = []
    for st in STAGES:
        state: D.DotState = "done" if st in seen or b["col"] == "done" else "todo"
        if b["col"] != "done" and st == cur:
            dot_map: dict[str, D.DotState] = {"live": "live", "wait": "you", "park": "you", "stuck": "bad"}
            state = dot_map.get(kind(last), state)
        out.append(D.PhaseDot(phase=st, state=state))
    return out


def totals(b: dict) -> D.Totals:
    mins = sum(s[2] - s[1] for s in work(b) if kind(s) != "gap")
    tok = int(mins * TOKENS_PER_MIN)
    tone = "bad" if tok >= 4 * USUAL else "watch" if tok >= 2 * USUAL else ""
    return D.Totals(secs=int(mins * 60), tokens=tok, usual=USUAL, usual_n=USUAL_N, tone=tone)


def card(b: dict, by: dict, waiters: dict) -> D.BeadCard:
    col = COLUMN[b["col"]]
    tone = "you" if b["col"] in ("ask", "look") else "bad" if b.get("bad") else "run" if b["col"] in ("working", "review") else ""
    waits = "no slot serves task-loop yet" if b["id"] == "tl-8k4" else ""
    return D.BeadCard(
        id=b["id"], project=b["proj"], title=b["t"], column=col, marker=marker(b, by),
        status=("⏩ " if b.get("soft") else "") + b["line"], tone=tone, t=ago(b["age"]) if b.get("age") else None,
        epic=EPICS.get(b["room"]), slot=b.get("slot") if b["col"] != "backlog" else None, lane=b.get("lane"),
        loops=b.get("loops", 0), dots=dots(b), needs=[n for n in b.get("needs", []) if n in by and by[n]["col"] != "done"],
        goal=b["short"].startswith("g"),
        waits_why=waits, ack=False, totals=totals(b) if work(b) else D.Totals(),
        assumptions={"6dq0": 2, "d5f.48": 1}.get(b["short"], 0), shots=b.get("shots", 0),
    )


def pieces(b: dict) -> list[D.Piece]:
    out: list[dict] = []
    cur = None
    for s in b.get("seg", []):
        sl = None if kind(s) == "gap" else (s[4] if len(s) > 4 and s[4] else b.get("slot"))
        if sl is None:
            cur = None
            continue
        if cur is None or cur["slot"] != sl:
            cur = {"slot": sl, "segs": []}
            out.append(cur)
        cur["segs"].append(s)
    res = []
    for i, p in enumerate(out):
        segs = [D.Seg(label=s[0], kind=KIND[kind(s)], t0=at(s[1]), t1=at(s[2])) for s in p["segs"]]
        res.append(D.Piece(bead=b["id"], project=b["proj"], slot=p["slot"], n=i, segs=segs,
                           from_slot=out[i - 1]["slot"] if i else None, to_slot=out[i + 1]["slot"] if i + 1 < len(out) else None,
                           landed=b["col"] == "done" and i == len(out) - 1))
    return res


def slots(data: dict, all_pieces: list[D.Piece]) -> list[D.Slot]:
    lanes = {ln["n"]: ln for ln in data["LANES"]}
    out = []
    for _machine, name, lane in data["SLOTS"]:
        state, bead, proj, t, why = "idle", None, None, None, f"no {lane} work ready"
        for p in all_pieces:
            if p.slot != name:
                continue
            w = [s for s in p.segs if s.kind != "projected"]
            if w and w[-1].t1 >= NOW >= w[-1].t0:
                k = w[-1].kind
                slot_map: dict[str, SlotState] = {"live": "running", "stuck": "stuck", "look": "look", "ask": "free"}
                state = slot_map.get(k, "running")
                bead, proj, t = p.bead, p.project, w[-1].t0
                why = f"{p.bead} parked here, waits on your answer" if k == "ask" else ""
        nxt = lanes[lane]["next"][0] if lane in lanes and lanes[lane]["next"] and state != "idle" else None
        out.append(D.Slot(id=name, name=name, lane=lane, state=state, project=proj, bead=bead, t=t, next=nxt, idle_why=why))
    return out


ASKS: dict[str, dict[str, Any]] = {  # keyed by the mock's short id
    "fld.27": {
        "question": "Which bills are monthly and which are weekly?", "cause": D.OwnerCause.REQUIREMENT,
        "why": 'The bead says "rent and bills every week", but phone and internet are monthly in real life.',
        "tried": ["read docs/design/economy.md: lists rent only", "balance tests fail if the period is guessed wrong"],
        "options": [("Rent weekly, phone and internet monthly", "Matches real life; 2 more tests", True),
                 ("Everything weekly", "Simplest; feels off for phone bills", False),
                 ("Everything monthly", "Changes the bead title; slower money pressure", False)],
        "similar": D.Similar(bead=L("a3k.1"), question="Monthly salary or weekly?", answer="weekly", t=NOW - 6 * 86400),
        "thread": [D.ThreadMsg(by="owner", t=NOW - 900, md="What does the design doc say about utilities?"),
                D.ThreadMsg(by="agent", t=NOW - 840, md="Nothing; it lists rent only (`docs/design/economy.md`).")], "ask_backs": 1},
    "a3k.2": {
        "question": 'Show real currency symbols, or "$" everywhere?', "cause": D.OwnerCause.DECISION,
        "blocking": False, "default": '"$" only',
        "why": 'The design doc mentions "$" only; real symbols need a locale table (about 1 more bead).',
        "options": [('"$" only for now', "No extra work; file a bead for locales", True),
                    ("Real symbols now", "+1 bead, about 1h", False)]},
}


def ask_card(b: dict) -> D.AskCard:
    if b["col"] == "look":
        return D.AskCard(id=f"{b['id']}-look", bead=b["id"], project=b["proj"], source="look", question="4 screens of the quit dialog",
                         t=ago(b["age"]), shots=[shot_url(b["id"], i) for i in range(b.get("shots", 4))])
    a = ASKS[b["short"]]
    return D.AskCard(
        id=f"{b['id']}-1", bead=b["id"], project=b["proj"], source="ask", question=a["question"], t=ago(b["age"]),
        blocking=a.get("blocking", True), why=a["why"], tried=a.get("tried", []), default=a.get("default", ""), owner_cause=a["cause"],
        options=[D.AskOptionCard(label=o[0], consequence=o[1], recommended=o[2]) for o in a["options"]],
        similar=a.get("similar"), thread=a.get("thread", []), ask_backs=a.get("ask_backs", 0))


def shot_url(bead: str, i: int) -> str:
    return f"/api/artifact?project=lifesim&bead={bead}&name=shot-{i + 1}.png"


def passes(b: dict) -> list[D.Pass]:
    raw: list[dict] = []
    cur: dict = {"c": {}, "end": "", "text": "", "segs": []}
    for s in work(b):
        n, a, e, k = s[0], s[1], s[2], kind(s)
        if k == "gap":
            continue
        if k in ("park", "parkx"):
            lane_out = "codex" in n
            cur["end"], cur["text"] = (
                ("lane_out", "lane ran out, parked") if lane_out else ("asked", "asking you" if k == "park" else "asked; answered")
            )
            cur["segs"].append(s)
            raw.append(cur)
            cur = {"c": {}, "end": "", "text": "", "segs": [], "resumed": lane_out}
            continue
        st = stage_of(n)
        if st is None:
            continue
        idx = STAGES.index(st)
        if (
            st in cur["c"]
            and idx <= max(STAGES.index(x) for x in cur["c"])
            and not (st == D.Phase.LOOK and n == "your look")
            and k != "stuck"
        ):
            raw.append(cur)
            cur = {"c": {}, "end": "", "text": "", "segs": []}
        prev = cur["c"].get(st, {"m": 0, "k": ""})
        cur["c"][st] = {"m": prev["m"] + (e - a), "k": k or prev["k"]}
        cur["segs"].append(s)
        if k == "f":
            cur["end"], cur["text"] = "test_failed", "test failed: back to write"
    if cur["c"] or not raw:
        raw.append(cur)
    if b["col"] == "done" and not raw[-1]["end"]:
        raw[-1]["end"], raw[-1]["text"] = "done", "landed"
    out = []
    evs = [(ago(e[0]), e) for e in b.get("ev", [])]
    for i, p in enumerate(raw):
        last = max((STAGES.index(x) for x in p["c"]), default=-1)
        cells = []
        for j, st in enumerate(STAGES):
            c = p["c"].get(st)
            if not c:
                cells.append(D.Cell(phase=st, state="skipped" if j < last else "empty"))
                continue
            secs, tok = int(c["m"] * 60), int(c["m"] * TOKENS_PER_MIN)
            cell_map: dict[str, D.CellState] = {"f": "failed", "live": "live", "wait": "you", "park": "you", "stuck": "stuck"}
            small: D.CellState = "small" if c["m"] < 10 and tok < 100_000 else "visited"
            state = cell_map.get(c["k"]) or small
            cells.append(D.Cell(phase=st, state=state, secs=secs, tokens=tok, last=""))
        t0 = at(p["segs"][0][1]) if p["segs"] else NOW
        t1 = at(p["segs"][-1][2]) if p["segs"] else NOW
        last_pass = i == len(raw) - 1
        msgs = [D.Msg(t=t, icon=e[1], who=e[2], md=md(e[3])) for t, e in evs if t0 <= t <= t1 or (last_pass and t >= t0)]
        resumed = D.Resumed(slot=b["slot"], branch=f"bd/{b['id']}", waited_secs=35 * 60) if p.get("resumed") else None
        out.append(D.Pass(n=i + 1, cells=cells, end=p["end"], end_text=p["text"], resumed=resumed, messages=msgs))
    return out


TERM = {L("5ban.3"): ["$ dotnet test --filter path_avoids_walls", "NavGrid: 48\u00d748 built in 12ms",
                   'path_avoids_walls ........ <span class="e">FAILED</span>', "  expected no wall tiles on path, found (12,7)",
                   '<span class="d">[agent] thinking…</span>', '<span class="d">[agent] thinking…</span>']}


def live_box(b: dict) -> D.LiveBox | None:
    w = work(b)
    if not w or b["col"] == "done" or w[-1][2] < 0:
        return None
    k, st = kind(w[-1]), stage_of(w[-1][0]) or D.Phase.WRITE
    n = len(passes(b))
    if k == "stuck":
        return D.LiveBox(kind="stuck", phase=st, pass_n=n, t=at(w[-1][1]), cmd="dotnet test --filter path_avoids_walls",
                         why="same test failed 3\u00d7, then 22m with no tool calls", silent_secs=22 * 60,
                         checks=D.CheckCount(passed=41, failed=1, total=42))
    if k == "live":
        review = st == D.Phase.REVIEW
        return D.LiveBox(kind="run", phase=st, pass_n=n, t=at(w[-1][1]),
                         cmd=f"claude -p review bd/{b['id']}" if review else f"codex exec write bd/{b['id']}",
                         tokens=84_000 if review else 312_000,
                         subtasks=[] if review else [D.Subtask(text="clamp mood at 0 outdoors", done=True),
                                                     D.Subtask(text="mood_rain_outdoor passes", done=False)])
    return None


def tone(line: str) -> TermTone:
    return "err" if "FAILED" in line else "ok" if 'class="o"' in line else "dim" if 'class="d"' in line else ""


def live_page(bead: str, lines: list[str], state: LiveState) -> D.LivePage:
    tl = [D.TermLine(t=NOW - (len(lines) - i) * 20, text=md(ln), tone=tone(ln)) for i, ln in enumerate(lines)]
    tools = []
    for i, ln in enumerate(lines):
        m = re.match(r"(read|edit)\s+(\S+)", md(ln))
        if m:
            tools.append(D.ToolCall(t=tl[i].t, name="Read" if m.group(1) == "read" else "Edit", arg=m.group(2)))
        elif md(ln).startswith("$ "):
            tools.append(D.ToolCall(t=tl[i].t, name="Bash", arg=md(ln)[2:]))
    return D.LivePage(cursor=f"{bead}:{len(lines)}", state=state, lines=tl, tools=tools)


def ledger(data: dict) -> list[D.LedgerRow]:
    days = {"today": 0, "yesterday": 1}
    out = []
    for when, bead, q, ans, oc, cause in data["LED"]:
        d = days.get(when.split()[0])
        if d is None:
            d = int(when.split()[0])
        t = NOW - d * 86400
        status_map: dict[str, AskStatus] = {"open": "open", "open (not blocking)": "open_soft"}
        status = status_map.get(ans, "answered")
        outcome, ref = None, ""
        for sym, st in (("📜", D.Stick.ADR), ("🛠", D.Stick.FACTORY), ("✏️", D.Stick.FIX), ("⬇", D.Stick.DEMOTE)):
            if oc.startswith(sym):
                outcome = st
                m = re.search(r"(ADR-\d+|fb\.\d+)", oc)
                ref = m.group(1) if m else ""
        if oc == "once":
            outcome = D.Stick.ONCE
        out.append(D.LedgerRow(t=t, ask=f"{bead}-1", bead=bead,
                               project="task-loop" if bead.startswith("tl-") else "lifesim", question=q, status=status,
                               answer="" if status != "answered" else ans,
                               outcome=outcome, outcome_ref=ref, cause=CAUSE.get(cause, D.OwnerCause.UNKNOWN)))
    return out


def adrs(data: dict) -> list[D.AdrRow]:
    out = []
    for aid, text, reuse, age in data["ADR"]:
        m = re.search(r"reused (\d+)", reuse)
        d = 0 if age == "today" else int(age.split()[0])
        out.append(D.AdrRow(id=aid, project="lifesim", text=text, t=NOW - d * 86400, reuses=int(m.group(1)) if m else 0,
                                 last_used=NOW - 86400 if m else None, prune="0 reuses in" in reuse))
    return out


def lanes(data: dict) -> list[D.LaneCard]:
    out = []
    for ln in data["LANES"]:
        lane_states: dict[str, LaneState] = {"": "ok", "w": "watch", "x": "locked"}
        st = lane_states[ln["st"]]
        hm = re.search(r"(\d\d):(\d\d)", ln["reset"])
        resets = NOW + 3600 * 2 if hm else None
        plan, _, model = ln["plan"].partition(" · ")
        out.append(D.LaneCard(id=ln["n"].replace(" ", "-").lower(), name=ln["n"], plan=plan, model=model, state=st,
                              window_pct=float(ln["h5"]), forecast_pct=float(ln["proj"]), resets_at=resets, week_pct=float(ln["wk"]),
                              locked_until=NOW + 3 * 86400 if st == "locked" else None, forecast=ln["fx"], slots=ln["slots"],
                              running=ln["run"], waiting=ln["next"], status_t=NOW - 300))
    return out


def learning() -> D.Learning:
    return D.Learning(
        weeks=[f"W{w}" for w in range(37, 45)],
        asks_per_landed=[1.4, 1.3, 1.1, 1.2, 0.9, 1.0, 0.9, 0.6], repeat_asks=[3, 2, 2, 1, 1, 0, 0, 2],
        sendbacks_per_bead=[0.5, 0.6, 0.4, 0.5, 0.4, 0.4, 0.4, 0.4], durable_pct=[10, 15, 20, 22, 30, 28, 30, 45],
        causes=[D.CauseCount(cause=c, now=n, prev=p) for c, n, p in (
            (D.OwnerCause.REQUIREMENT, 4, 2), (D.OwnerCause.DECISION, 3, 4), (D.OwnerCause.UNKNOWN, 2, 0),
            (D.OwnerCause.ENVIRONMENT, 1, 2), (D.OwnerCause.PROCESS, 1, 1))])


def full_ids(data: dict) -> dict:
    """The mock's short bead ids become the real <project>-<id>; `short` keeps the mock's id for the lookups keyed by it."""
    proj = {b["id"]: b["proj"] for b in data["B"]}
    for b in data["B"]:
        b["short"] = b["id"]
        b["id"] = full(b["proj"], b["id"])
        b["needs"] = [full(proj[n], n) for n in b.get("needs", [])]
    data["TERM"] = {full(proj[k], k): v for k, v in data["TERM"].items()}
    for row in data["LED"]:
        row[1] = full(proj.get(row[1], "lifesim"), row[1])
    for ln in data["LANES"]:
        ln["run"] = [full(proj.get(b, "lifesim"), b) for b in ln["run"]]
        ln["next"] = [full(proj.get(b, "lifesim"), b) for b in ln["next"]]
    return data


def needs(cards: list[Any]) -> list[NeedRow]:
    """One row of each kind of the needs-you list (the beads are the first cards of the fixture)."""
    ids = [c.id for c in cards[:4]]
    return [
        NeedRow(kind="stalled", project="lifesim", bead=None, why="2 ready bead(s), nothing happened for 40 min", since=NOW - 2400),
        NeedRow(kind="label", project="lifesim", bead=ids[0], why="needs acceptance criteria", since=NOW - 7200, title="needs-ac"),
        NeedRow(kind="block", project="lifesim", bead=ids[1], why="needs a human: pick the save format", since=NOW - 5400),
        NeedRow(kind="parked", project="lifesim", bead=ids[2], why="ended on a question twice with this text", since=NOW - 3600),
        NeedRow(kind="capped", project="lifesim", bead=ids[3], why="3 runs, the cap", since=NOW - 3000),
        NeedRow(kind="slot_aside", project="lifesim", bead=None, why="slot a: 3 runs failed within 5 min each", since=NOW - 1200,
                   until=NOW + 9000),
        NeedRow(kind="slot_held", project="lifesim", bead=None, why="slot b: testing by hand", since=NOW - 900, until=NOW + 1800),
        NeedRow(kind="slot_setup", project="lifesim", bead=None, why="slot c: setup failed (exit 1)", since=NOW - 600),
        NeedRow(kind="stray", project="lifesim", bead=ids[0], why="claimed by tl-x, no live run (lease ended)"),
        NeedRow(kind="paused", project="", bead=None, why="lane codex is out", until=NOW + 5400),
        NeedRow(kind="absent", project="task-loop", bead=None, why="3 ready bead(s) and no loop alive", since=NOW - 7200),
    ]


def build() -> dict[str, Any]:
    """Every fixture: relative path -> record."""
    data = full_ids(json.loads((DIR / "mock-8b.json").read_text(encoding="utf-8")))
    beads = data["B"]
    by = {b["id"]: b for b in beads}
    waiters: dict[str, list[str]] = {}
    for b in beads:
        for n in b.get("needs", []):
            waiters.setdefault(n, []).append(b["id"])
    cards = [card(b, by, waiters) for b in beads]
    all_pieces = [p for b in beads for p in pieces(b)]
    epics: dict[str, dict[str, Any]] = {}
    for b in beads:
        e = EPICS[b["room"]]
        ep = epics.setdefault(e, {"project": b["proj"], "title": b["room"], "done": 0, "total": 0})
        ep["total"] += 1
        ep["done"] += b["col"] == "done"
    snap = D.Snapshot(
        version="fx-1", t=NOW,
        server=D.ServerInfo(version="0000fixture", host="mac", loops=[
            D.LoopInfo(project="lifesim", running=True, last_activity=NOW - 4, ready=2, quiet_since=NOW - 2400, health="stalled"),
            D.LoopInfo(project="task-loop", running=False, last_activity=NOW - 7200, ready=3, health="absent"),
        ]), needs=needs(cards),
        projects=[D.Project(id="lifesim", name="lifesim"), D.Project(id="task-loop", name="task-loop")],
        epics=[D.Epic(id=k, project=v["project"], title=v["title"], done=v["done"], total=v["total"]) for k, v in epics.items()],
        slots=slots(data, all_pieces), beads=cards, pieces=all_pieces,
        asks=[ask_card(b) for b in beads if b["col"] in ("ask", "look")],
        ledger=ledger(data), adrs=adrs(data), learning=learning(), lanes=lanes(data))
    out: dict[str, Any] = {"snapshot.json": snap}
    for b, c in zip(beads, cards, strict=True):
        if not b.get("seg"):
            continue
        arts = [D.Artifact(name=f"shot-{i + 1}.png", url=shot_url(b["id"], i), kind="image", t=NOW - 360, pass_n=len(passes(b)),
                           phase=D.Phase.LOOK) for i in range(b.get("shots", 0))]
        out[f"bead/{b['id']}.json"] = D.BeadDetail(
            t=NOW, card=c, description=f"{b['t']}. Part of {b['room']}.",
            acceptance="- works in a new save and an old one\n- tests cover the rule\n- no new warnings in the build",
            comments=[D.Msg(t=ago(e[0]), icon=e[1], who=e[2], md=md(e[3])) for e in b.get("ev", [])],
            passes=passes(b), artifacts=arts, waits_for=c.needs, unblocks=waiters.get(b["id"], []),
            live=live_box(b), ask=ask_card(b) if b["col"] in ("ask", "look") else None)
    for bid, lines in {**data["TERM"], **TERM}.items():
        out[f"live/{bid}.json"] = live_page(bid, lines, "live")
    out["writes.json"] = {
        "answer": D.AnswerReq(project="lifesim", ask=L("fld.27") + "-1", kind="answer", option=0),
        "look": D.LookReq(project="lifesim", bead=L("d5f.48"), verdict="redo", note="the confirm button is cut off"),
        "stick": D.StickReq(project="lifesim", ask=L("fld.27") + "-1", outcome=D.Stick.ADR),
        "cause": D.CauseReq(project="lifesim", bead=BeadId(L("5ban.3")), cause=D.OwnerCause.FLAKY_TEST),
        "ack": D.AckReq(project="lifesim", bead=BeadId(L("5ban.3")), ack=True),
        "prune": D.PruneReq(project="lifesim", adr="ADR-007"),
        "park": D.ParkReq(project="lifesim", bead=BeadId(L("6dq0"))),
        "stop": D.StopReq(project="lifesim", bead=BeadId(L("6dq0"))),
        "note": D.NoteReq(project="lifesim", bead=BeadId(L("6dq0")), text="keep the old save format readable"),
    }
    out["cost.json"] = cost_page()
    out["result.json"] = D.Result(ok=True, message="Sent. lifesim-fld.27 resumes in its slot.")
    return out


def cost_page() -> DC.CostPage:
    """Seven days of a few beads: one cost unknown (its calls are counted apart, never summed as 0)."""
    def row(key: str, secs: int, tokens: int, cost: float, calls: int, unknown: int = 0, bead: str = "") -> DC.CostRow:
        return DC.CostRow(key=key, secs=secs, tokens=tokens, cost=cost, calls=calls, unknown=unknown, bead=bead)
    return DC.CostPage(
        t=NOW, window="7d", runs=4,
        stages=[row("write", 5400, 700_000, 6.1, 6, 1), row("plan", 1500, 190_000, 0.9, 3), row("test", 900, 0, 0.0, 0),
                row("review", 600, 70_000, 0.0, 2, 2), row("land", 80, 0, 0.0, 0)],
        beads=[row("lifesim-d5f.58", 6300, 760_000, 5.5, 8, 2), row("lifesim-d5f.56", 2180, 200_000, 1.5, 3, 1)],
        drill=[row("write", 4000, 500_000, 4.5, 4, 1, "lifesim-d5f.58"), row("plan", 900, 120_000, 0.5, 2, 0, "lifesim-d5f.58"),
               row("review", 600, 70_000, 0.0, 2, 2, "lifesim-d5f.58")],
        waits=[row("lane", 1800, 0, 0.0, 0), row("resource", 120, 0, 0.0, 0)])


def encode(obj: Any) -> str:
    if isinstance(obj, dict):
        return json.dumps({k: wire.dump(v) for k, v in obj.items()}, ensure_ascii=False, indent=1) + "\n"
    return json.dumps(wire.dump(obj), ensure_ascii=False, indent=1) + "\n"


def write() -> list[str]:
    names = []
    for rel, obj in build().items():
        p = DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(encode(obj), encoding="utf-8")
        names.append(rel)
    return names


if __name__ == "__main__":
    print("\n".join(write()))
