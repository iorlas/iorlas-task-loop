"""One bead for the Roadmap's panel: what bd says (description, acceptance, comments, dependencies) and every run of the engine on it."""

from typing import Any

from taskloop_dash.api.artifacts import Artifacts
from taskloop_dash.api.tasks import Tasks
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.views import bead_blocks, names, segments
from taskloop_dash.views import timeline as tlv


class BeadApi:
    def __init__(self, env: Env, records: Records, beads: Beads, runlogs: RunLogs, tasks: Tasks,
                 artifacts: Artifacts) -> None:
        self.env, self.records, self.beads, self.runlogs, self.tasks, self.artifacts = env, records, beads, runlogs, tasks, artifacts

    def bead_runs(self, bead: str, alive: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Every engine run of the bead, oldest first: why it started, its blocks with outcome, arrow, time and tokens. -> (runs,
        the run timelines for segments.bead_segments). The last run is alive when the bead is running: its open step ends now."""
        runs: list[dict[str, Any]] = []
        tls: list[dict[str, Any]] = []
        prev: dict[str, Any] | None = None
        logs = self.records.engine_logs(retain=False).get(bead, [])
        for n, p in enumerate(logs):
            r = self.runlogs.run_timeline(p, alive=alive and n == len(logs) - 1)
            tls.append(r)
            r["because"] = tlv.because_text(r, prev)
            prev = r
            runs.append({"run": r["run"], "because": r["because"], "started": r["started"], "secs": r["secs"], "tokens": r["tokens"],
                         "end": r["end"].get("text") or r["end"].get("outcome"), "outcome": r["end"].get("outcome"),
                         "blocks": bead_blocks.trail(r["blocks"], full=True)})
        return runs, tls

    def api_bead(self, repo: str, bead: str) -> dict[str, Any]:
        self.env.touch()
        if not names.is_bead_id(bead):  # an id is never a bd option
            return {"id": bead, "found": False, "error": "not a bead id"}
        path = self.beads.resolve_repo(repo, bead)

        def load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            return self.beads.show(path, bead) or {}, self.beads.comments(path, bead)
        b, comments = self.env.ttl.get(f"bead:{path}:{bead}", 15, load)
        try:
            alive = any(t["id"] == bead and t.get("state") == "running" for t in self.tasks.api_tasks()["tasks"])
        except Exception:
            alive = False
        runs, tls = self.env.ttl.get(f"beadruns:{path}:{bead}:{int(alive)}", 5 if alive else 15, lambda: self.bead_runs(bead, alive))
        deps = [{k: d.get(k) for k in ("id", "title", "status", "type")} for d in (b.get("dependencies") or [])]
        return {"id": bead, "title": b.get("title") or "", "status": b.get("status"), "priority": b.get("priority"),
                "labels": b.get("labels") or [], "assignee": b.get("assignee"), "created_at": b.get("created_at"),
                "description": b.get("description") or "", "notes": b.get("notes") or "",
                "acceptance": b.get("acceptance_criteria") or "", "design": b.get("design") or "", "deps": deps,
                "comments": [{"author": c.get("author"), "text": c.get("text"), "at": c.get("created_at")} for c in comments],
                "artifacts": self.artifacts.listing(bead), "runs": runs, "found": bool(b),
                "timeline": segments.bead_segments(tls, self.env.clock())}
