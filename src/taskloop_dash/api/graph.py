"""The Plan tab: one repo's open beads (plus the last day's closes) as nodes, blocking dependencies as edges."""

from typing import Any

from taskloop_dash.api.asks import Asks
from taskloop_dash.api.tasks import Tasks
from taskloop_dash.env import Bead, Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.records import Records
from taskloop_dash.views import graph

Cfg = dict[str, Any]


class Graph:
    def __init__(self, env: Env, records: Records, beads: Beads, tasks: Tasks, asks: Asks) -> None:
        self.env, self.records, self.beads, self.tasks, self.asks = env, records, beads, tasks, asks

    def loop_order(self, repo: str, beads: list[Bead], cfg: Cfg) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """([(id, reason)] in the order the loop takes them, [(id, why skipped)]). graph.local_queue is the only rule here; P2 replaces
        it with LoopState.queue, the order the loop itself wrote."""
        pri = {b["id"]: b.get("priority") if b.get("priority") is not None else 2 for b in beads}
        ids = graph.local_queue(beads, cfg)
        return [(i, "") for i in sorted(ids, key=lambda i: (pri[i], i))], []

    def loop_queue(self, repo: str, beads: list[Bead], cfg: Cfg) -> set[str]:
        """The ids the loop would take."""
        return {i for i, _ in self.loop_order(repo, beads, cfg)[0]}

    def config_of(self, path: str) -> Cfg:
        try:
            return self.env.ports.load_cfg(path)
        except Exception:
            return {"pick_label": "auto", "skip_labels": []}

    def api_graph(self, repo: str = "") -> dict[str, Any]:
        self.env.touch()
        known = self.records.repos()
        path = self.beads.resolve_repo(repo, "") if repo else (known[0] if known else "")
        names = [basename(p) for p in known]
        if not path:
            return {"repo": "", "repos": names, "nodes": [], "edges": [], "summary": {}, "error": "no such repo"}
        beads = self.beads.beads_of(path)

        def build() -> dict[str, Any]:
            cfg = self.config_of(path)
            run = {t["id"] for t in self.tasks.api_tasks()["tasks"] if t.get("state") == "running"}
            ask_ids = {b["id"] for b in beads if b.get("status") != "closed" and self.asks.open_ask(b["id"])}
            return graph.build(beads, cfg, self.loop_queue(path, beads, cfg), run, ask_ids, repo=basename(path))

        return dict(self.env.ttl.get("graph:" + path, 5, build), repos=names)
