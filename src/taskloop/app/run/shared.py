"""Notes shared by the tasks of one repo (docs/design/stages.md section 6): the tests known to be flaky, the tasks running beside this
one, what landed on the base since this branch left it."""
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json

from taskloop.adapters import ident
from taskloop.adapters.gitrepo import same_dir
from taskloop.app.slots import engine_lock

FLAKE_DAYS = 14  # how long a writer-reported flaky test stays in the shared notes


def one_line(text: object, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


class Shared:
    def __init__(self, host: Any) -> None:
        self.e = host

    def shared_path(self) -> Path:
        e = self.e
        common = e.git("rev-parse", "--path-format=absolute", "--git-common-dir") or str(e.wt)
        return ident.config_dir() / "shared" / f"{hashlib.sha1(common.encode('utf-8')).hexdigest()[:12]}.json"

    def known_flakes(self) -> list[dict[str, Any]]:
        """[{test, note, bead}]: tests known to fail without cause. A writer reports one (flakes); the owner may edit the file."""
        try:
            data = json.loads(self.shared_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        week2 = time.time() - FLAKE_DAYS * 86400  # a writer's word is not a fact for ever: it lapses unless reported again
        return [f for f in (data.get("flakes") if isinstance(data, dict) else None) or []
                if isinstance(f, dict) and str(f.get("test") or "").strip() and (f.get("t") or 0) >= week2]

    def add_flakes(self, new: list[Any]) -> None:
        e = self.e
        have = {one_line(f["test"], 10_000) for f in self.known_flakes()}
        add = [{"test": one_line(f["test"], 200), "note": one_line(f.get("note"), 300), "bead": e.bead, "t": int(time.time())}
               for f in [x for x in new if isinstance(x, dict)][:3] if str(f.get("test") or "").strip()]  # three a write
        add = [f for f in add if f["test"] not in have]
        if not add or e.dry:
            return
        path = self.shared_path()
        try:  # read again just before the write: another slot may have added one meanwhile
            path.parent.mkdir(parents=True, exist_ok=True)
            cur = self.known_flakes()
            seen = {f["test"] for f in cur}
            atomic_write_json(path, {"flakes": (cur + [f for f in add if f["test"] not in seen])[-40:]}, indent=1)
            e.log.note("known flaky: " + "; ".join(f["test"] for f in add))
        except OSError:
            pass

    def siblings(self) -> list[tuple[str, str, list[str]]]:
        """[(bead, summary, files)]: tasks running in other worktrees of this repo right now (a live engine lock)."""
        e = self.e
        out: list[tuple[str, str, list[str]]] = []
        for line in e.git("worktree", "list", "--porcelain").splitlines():
            if not line.startswith("worktree "):
                continue
            wt = line[len("worktree "):]
            if same_dir(wt, e.wt):
                continue
            lock = engine_lock.peek_engine_lock(wt)
            if lock is None or not lock.bead or lock.bead == e.bead or not engine_lock.live(lock):
                continue
            ck = e.stores.checkpoints.of(lock.bead).get()
            plan = (ck.state.plan_data if ck else None) or {}
            files = list(dict.fromkeys(f for st in plan.get("stages") or [] for f in st.get("files") or []))
            out.append((lock.bead, one_line(plan.get("summary"), 100), files[:6]))
        return out[:5]

    def landed_since(self) -> list[str]:
        """Subjects of what landed on the base since this task's branch left it (as far as the last fetch knows)."""
        e = self.e
        log = e.git("log", "--format=%s", "-n", "8", f"{e.checkout.base_sha()}..{e.cfg.base}")
        return [x[:100] for x in log.splitlines() if x.strip()]

    def flakes_text(self) -> str:
        flakes = self.known_flakes()
        if not flakes:
            return ""
        rows = "".join(f"- {f['test'][:120]}{(': ' + f['note'][:160]) if f.get('note') else ''}"
                       f"{(' (found in ' + f['bead'] + ')') if f.get('bead') else ''}\n" for f in flakes[-8:])
        return ("\nKnown flaky tests of this repo (a writer reported each; they fail without a cause in the change). A check red only "
                "on one: run it once more and say so in your summary; do not build a new isolation or fix for it unless the task "
                f"is about it:\n{rows}")

    def shared_text(self) -> str:
        """What the other tasks of this repo are doing, for the planner and a writer's first prompt: running now, landed since
        this branch left the base, known flaky tests. '' when there is nothing to say."""
        out = []
        sib = self.siblings()
        if sib:
            rows = "".join(f"- {b}{(': ' + sm) if sm else ''}{(' [files: ' + ', '.join(fs) + ']') if fs else ''}\n" for b, sm, fs in sib)
            out.append("Running now beside this task (do not edit their files unless this task needs them; "
                       "do not redo their work):\n" + rows)
        landed = self.landed_since()
        if landed:
            out.append(f"Landed on {self.e.cfg.base} since this branch left it:\n" + "".join(f"- {x}\n" for x in landed))
        flakes = self.flakes_text()
        return ("\n" + "".join(out) + flakes) if (out or flakes) else ""
