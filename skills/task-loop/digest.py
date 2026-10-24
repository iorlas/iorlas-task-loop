"""tl digest: the morning digest of the night (tl-bxk.12.2) and the refusals, DNS errors and flakes of the window
(tl-bxk.8.25), for the owner and the coordinator.

  tl.py digest [--since T] [--until T] [--print] [--send]   default: print. --send pushes it through notifier.py once.
  The loop calls maybe_send() on every pass: after DIGEST_HOUR local time, once a day, covering the time since the last one.

Reads only: report.scorecard (traces, bd), the asks folder, the engine logs and their stderr. State: ~/.config/task-loop/digest.json.
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import notifier
import tl

DIGEST_HOUR = 7
REFUSED = re.compile(r"\b(?:denied|refused)\b", re.I)
DNS = re.compile(r"Could not resolve host|Temporary failure in name resolution|getaddrinfo|nodename nor servname|"
                 r"Name or service not known", re.I)
FLAKE = re.compile(r"\bflak(?:y|e|es)\b|passed on (?:a )?retry|succeeded on retry", re.I)
ENGINE_KINDS = ("warn", "note", "transition")  # written by the engine itself, not model prose or a quoted command


def state_path():
    return tl.config_dir() / "digest.json"


def read_state():
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def repos():
    try:
        d = json.loads((tl.config_dir() / "repos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in d if (Path(p) / ".beads").is_dir()] if isinstance(d, dict) else []


def signals(since, until, engine_dir=None):
    """{refused|dns|flake: {count, beads: {bead: n}, example}} from the engine logs touched in the window."""
    out = {k: {"count": 0, "beads": {}, "example": ""} for k in ("refused", "dns", "flake")}
    d = Path(engine_dir) if engine_dir else tl.config_dir() / "engine"
    for f in sorted(glob.glob(str(d / "*.jsonl")) + glob.glob(str(d / "*.stderr"))):
        try:
            if Path(f).stat().st_mtime < since:
                continue
            lines = Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        bead = re.sub(r"-\d{8}-\d{6}\.\w+$", "", Path(f).name)
        for ln in lines:
            text, t = ln, None
            if f.endswith(".jsonl"):
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(r, dict) or r.get("kind") not in ENGINE_KINDS:
                    continue
                text, t = str(r.get("text") or ""), r.get("t")
            if t is not None and not (since <= float(t) <= until):
                continue
            for name, rx in (("refused", REFUSED), ("dns", DNS), ("flake", FLAKE)):
                if rx.search(text):
                    s = out[name]
                    s["count"] += 1
                    s["beads"][bead] = s["beads"].get(bead, 0) + 1
                    s["example"] = s["example"] or " ".join(text.split())[:140]
    return out


def open_asks(limit=3):
    """(open count, parked count, the first `limit` as 'bead: headline') from the dashboard's own inbox."""
    try:
        rows = tl.dash_module().inbox()
    except Exception:  # a digest never fails over the asks
        return 0, 0, []
    live = [r for r in rows if not r.get("parked")]
    top = []
    for r in live[:limit]:
        head = (r.get("question") or "").splitlines()[0].replace("**", "") if r.get("question") else ""
        top.append("%s: %s%s" % (r.get("bead"), head[:90], " (unblocks %d)" % r["unblocks"] if r.get("unblocks") else ""))
    return len(live), len(rows) - len(live), top


def compose(since, until, scorecards=None, sig=None, asks=None):
    """-> (one line for a push, the whole text). Pure given its inputs: tests pass them in."""
    if scorecards is None:
        import report
        scorecards = []
        for repo in sorted(repos()):
            try:
                scorecards.append(report.scorecard(repo, since, until, base=report.default_base(repo), alive=report.run_alive))
            except Exception:  # one repo's bd failing leaves the others
                continue
    sig = signals(since, until) if sig is None else sig
    n_open, n_parked, top = open_asks() if asks is None else asks
    tot = {k: sum(c.get(k, 0) for c in scorecards) for k in ("beads", "landed", "landed_no_ask", "parked", "paused", "failed",
                                                              "crashes", "lost")}
    hours = max(1, round((until - since) / 3600))
    one = "last %dh: %d landed, %d asks open, %d paused, %d failed" % (hours, tot["landed"], n_open, tot["paused"], tot["failed"])
    lines = ["task-loop, the last %d hours" % hours, "",
             "- landed %d of %d beads (%d with no ask)" % (tot["landed"], tot["beads"], tot["landed_no_ask"]),
             "- asked and waiting: %d%s" % (n_open, " (+%d parked after 3 days)" % n_parked if n_parked else ""),
             "- paused %d, failed %d, crashes %d, lost work %d" % (tot["paused"], tot["failed"], tot["crashes"], tot["lost"])]
    for c in scorecards:
        lines.append("  %s: %d landed, %d failed" % (Path(c["repo"]).name, c["landed"], c["failed"]))
    if top:
        lines += ["", "Asks to answer first:"] + ["- " + x for x in top]
    lines += ["", "For the coordinator:"]
    for name, label in (("refused", "commands refused"), ("dns", "DNS or network errors"), ("flake", "flakes retried")):
        s = sig[name]
        worst = ", ".join("%s x%d" % kv for kv in sorted(s["beads"].items(), key=lambda kv: -kv[1])[:3])
        lines.append("- %s: %d%s" % (label, s["count"], (" (%s)" % worst) if worst else ""))
    return one, "\n".join(lines)


def due(now=None, hour=DIGEST_HOUR):
    """(since, until) when a digest is due now, else None: after `hour` local time and not yet sent today."""
    now = now or time.time()
    lt = datetime.fromtimestamp(now)
    at = lt.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()
    st = read_state()
    last, tried = float(st.get("sent") or 0), float(st.get("tried") or 0)
    if now < at or last >= at or now - tried < 2 * 3600:  # not yet, done today, or a try is running or failed lately
        return None
    return (last if last and now - last < 3 * 86400 else now - 86400), now


def send(since, until):
    one, full = compose(since, until)
    got = notifier.send("digest", one, full=full)
    if got == "sent":
        try:
            state_path().write_text(json.dumps({"sent": until, "tried": time.time(), "line": one}), encoding="utf-8")
        except OSError:
            pass
    return got, full


def maybe_send(now=None):
    """The loop's call: once a day after DIGEST_HOUR, when a channel is set, a detached `tl digest --send` (composing reads bd
    for every bead of the window and takes minutes: a loop pass never waits for it). -> 'started' or ''."""
    w = due(now)
    if not w or notifier.channel()[0] == "off":
        return ""
    st = read_state()
    st["tried"] = now or time.time()
    try:
        state_path().write_text(json.dumps(st), encoding="utf-8")
        cmd = [sys.executable, str(Path(__file__).resolve().with_name("tl.py")), "digest", "--send",
               "--since", str(int(w[0])), "--until", str(int(w[1]))]
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=(os.name != "nt"))
    except OSError:
        return ""
    return "started"


def cmd_digest(a):
    now = time.time()
    import report

    def at(text, default, forward=False):
        if not text:
            return default
        return float(text) if re.match(r"^\d{9,}(\.\d+)?$", text.strip()) else report.parse_time(text, now, forward=forward)
    since, until = at(a.since, now - 86400), at(a.until, now, True)
    if a.send:
        got, full = send(since, until)
        print("digest: %s" % got)
        return 0 if got in ("sent", "off") else 1
    print(compose(since, until)[1])
    return 0
