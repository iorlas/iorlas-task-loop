"""The reflect digest's rules: which went_badly items are one cause, which causes recur, and how a bead for one reads. Pure.

The engine's per-run reflections (traces.jsonl, read by app/report/reflect.py) are clustered by cause class and by what they say (or
the files they name); a cause that recurs in MIN_RUNS or more runs earns one bead with the run ids as evidence and acceptance criteria."""
from collections import Counter
from collections.abc import Iterable
from typing import Any, Final

from taskloop.domain.report import matchers

MIN_RUNS: Final = 2
SIMILAR: Final = 0.35  # token overlap (Jaccard) that makes two went_badly items one cause
FILE_SIMILAR: Final = 0.1  # ... or this much when they also name the same file (a bare tl.py or README.md must not merge unrelated items)
TITLE_SIMILAR: Final = 0.5  # ... and an open bead's title the same as a cluster
OWNERS: Final = {"engine": "iorlas-task-loop", "prompt": "iorlas-task-loop", "delegate": "iorlas-delegate"}
STOP: Final = frozenset({
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "was",
    "were",
    "has",
    "had",
    "not",
    "but",
    "are",
    "its",
    "into",
    "then",
    "than",
    "when",
    "after",
    "before",
    "each",
    "have",
    "been",
    "run",
    "runs",
    "session",
    "step",
    "bead",
    "one",
    "two",
    "still",
    "more",
    "over",
    "only",
    "also",
    "because",
    "while",
    "which",
    "they",
    "their",
    "there",
    "about",
})


def tokens(text: object) -> set[str]:
    return matchers.words(text) - STOP


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / float(len(a | b)) if a and b else 0.0



def items_of(rows: Iterable[Any], since: float, until: float) -> list[dict[str, Any]]:
    """The went_badly items of the reflected runs (trace rows, dicts) ended in the window, oldest first."""
    out: list[dict[str, Any]] = []
    for r in rows:
        refl = r.get("reflection") if isinstance(r, dict) else None
        if not isinstance(refl, dict):
            continue
        t = r.get("ended") or r.get("started") or 0
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if not since <= t <= until:
            continue
        for b in refl.get("went_badly") or []:
            if not isinstance(b, dict) or not b.get("what"):
                continue
            text = "{} {}".format(b.get("what"), b.get("evidence") or "")
            out.append(
                {
                    "cause": str(b.get("cause") or "other"),
                    "what": str(b["what"]),
                    "evidence": str(b.get("evidence") or ""),
                    "session": str(b.get("session") or ""),
                    "run": str(r.get("run") or ""),
                    "bead": str(r.get("bead") or ""),
                    "repo": str(r.get("repo_url") or ""),
                    "t": t,
                    "tokens": tokens(b["what"]),
                    "files": matchers.files_named(text),
                }
            )
    return sorted(out, key=lambda i: i["t"])


def cluster(its: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy, per cause class: an item joins the cluster of any item it shares a file with or says nearly the same as."""
    cl: list[dict[str, Any]] = []
    for it in its:
        for c in cl:
            if c["cause"] == it["cause"] and any(jaccard(it["tokens"], m["tokens"]) >= SIMILAR or
                                                 (it["files"] & m["files"] and jaccard(it["tokens"], m["tokens"]) >= FILE_SIMILAR)
                                                 for m in c["items"]):
                c["items"].append(it)
                break
        else:
            cl.append({"cause": it["cause"], "items": [it]})
    out: list[dict[str, Any]] = []
    for c in cl:
        m = c["items"]
        runs = sorted({i["run"] for i in m if i["run"]})
        counts = Counter(w for i in m for w in i["tokens"])
        out.append({"cause": c["cause"], "title": min((str(i["what"]) for i in m), key=len)[:100], "runs": runs,
                    "beads": sorted({i["bead"] for i in m if i["bead"]}), "repos": Counter(i["repo"] for i in m if i["repo"]),
                    "files": sorted(set().union(*[i["files"] for i in m]))[:8], "items": m,
                    "tokens": {w for w, _ in counts.most_common(12)}, "last": max(i["t"] for i in m)})
    return sorted(out, key=lambda c: (-len(c["runs"]), c["cause"]))


def is_recurring(c: dict[str, Any]) -> bool:
    """Two beads show it, or one bead's run did it three times: one retried bead with one complaint is a bead's problem."""
    runs = c["runs"] if isinstance(c.get("runs"), list) else c["run_ids"]
    return len(runs) >= 3 or (len(runs) >= MIN_RUNS and len(c["beads"]) >= 2)


def recurring(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in clusters if is_recurring(c)]


def same_cause(e: dict[str, Any], c: dict[str, Any]) -> bool:
    t = jaccard(set(e.get("tokens") or []), c["tokens"])
    return t >= SIMILAR or bool(set(e.get("files") or []) & set(c["files"]) and t >= FILE_SIMILAR)


def evidence_lines(c: dict[str, Any]) -> list[str]:
    out = []
    for i in c["items"][:8]:
        out.append("- run {} (bead {}, session {}): {}{}".format(i["run"] or "?", i["bead"] or "?", i["session"] or "run", i["what"][:200],
                                                           " | evidence: " + i["evidence"][:200] if i["evidence"] else ""))
    return out


def description(c: dict[str, Any], old: str = "") -> str:
    where = (" Files named: {}.".format(", ".join(c["files"]))) if c["files"] else ""
    return (
        "Recurring cause ({}) in {:d} runs, from the engine's run reflections (tl reflect digest).{}{}\n\nEvidence:\n{}\n\n"
        "Runs: {}\nTrace: `tl trace <bead>` lists each run's worker sessions."
    ).format(
        c["cause"],
        len(c["runs"]),
        where,
        (f" Recurred after {old} was closed.") if old else "",
        "\n".join(evidence_lines(c)),
        ", ".join(c["runs"]),
    )


def acceptance(c: dict[str, Any]) -> str:
    return ("The cause no longer shows in new reflections: after the fix, the next 3 runs of comparable beads (e.g. {}) end with no "
            "went_badly item of cause '{}' saying: {}".format(c["beads"][0] if c["beads"] else "the beads above", c["cause"], c["title"]))

