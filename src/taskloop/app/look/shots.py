"""The pictures of a visual change: which stages are visual, the shot methods the repo can render, the engine's own renders,
the writer's evidence, and the copies kept as artifacts."""
import glob
import os
from pathlib import Path
from typing import Any

from taskloop.adapters import looks
from taskloop.app.artifacts import store
from taskloop.app.artifacts.keep import Keeper
from taskloop.app.look.host import LookHost, LookPorts
from taskloop.app.look.state import LookState
from taskloop.contracts.artifact import ArtifactMeta, ArtifactSlot
from taskloop.contracts.gitport import Git
from taskloop.contracts.plancheck import StageData
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.stagefacts import RunFacts
from taskloop.contracts.wire import Refused
from taskloop.domain.checks.matchers import glob_re
from taskloop.domain.look.matchers import safe_name

IMAGE_EXT = (".png", ".jpg", ".jpeg")
IMAGE_KINDS = ("png", "jpg", "gif", "webp")
MAX_SHOTS, MAX_SHOT_BYTES = 20, 5 * 1024 * 1024


def visual_hit(vp: Any, paths: Any) -> bool:
    """True when a path matches an include glob and no exclude glob."""
    inc = [glob_re(g) for g in vp.include] if vp else []
    exc = [glob_re(g) for g in vp.exclude] if vp else []
    return any(any(r.match(p) for r in inc) and not any(r.match(p) for r in exc) for p in paths)


class Pictures:
    def __init__(self, facts: RunFacts, ports: LookPorts, state: LookState, hand: LookHost, git: Git) -> None:
        self.facts, self.ports, self.state, self.hand = facts, ports, state, hand
        self.git = git
        self.kept: Keeper | None = None

    @property
    def stale(self) -> bool:
        """Code changed after the last render: the pictures show an older tree."""
        return self.hand.render_stale

    def mark_stale(self) -> None:
        """Write's one word to the look stage after a write: its pictures are old now (the flag is checkpointed)."""
        self.hand.render_stale = True

    def keeper(self) -> Keeper:
        """This run's evidence budget: it writes the worktree's evidence dir and the run dir's; earlier runs are only looked at."""
        facts = self.facts
        if self.kept is None:
            earlier = sorted(d / "evidence" for d in facts.run_dir.parent.glob(glob.escape(facts.bead) + "-*") if d != facts.run_dir)
            self.kept = Keeper([facts.evidence_dir, facts.run_dir / "evidence"], earlier, int(facts.cfg.evidence_cap_mb) << 20)
        return self.kept

    def note_dropped(self) -> None:
        k = self.keeper()
        if k.dropped:
            self.ports.log.note(f"evidence over the {k.cap >> 20} MB cap: {k.dropped} file(s) not kept")

    def visual_cfg(self):
        facts = self.facts
        vp = facts.cfg.visual_paths
        return vp if vp and vp.include else None

    def shots(self) -> list[str]:
        """The pictures the writer saved under the evidence dir, relative to it."""
        facts, ports, state = self.facts, self.ports, self.state
        if not facts.evidence_dir.is_dir():
            return []
        out: list[str] = []
        for f in sorted(facts.evidence_dir.rglob("*")):
            if not (f.is_file() and f.suffix.lower() in IMAGE_EXT):
                continue
            rel = str(f.relative_to(facts.evidence_dir))
            if self.shot_methods() and rel not in state.rendered:
                continue  # with a shot table the pictures are the engine's own, of this run: never a writer's or an older run's
            why = f"over {MAX_SHOT_BYTES >> 20} MB" if f.stat().st_size > MAX_SHOT_BYTES else (
                f"more than {MAX_SHOTS} screenshots" if len(out) >= MAX_SHOTS else "")
            if why:
                if rel not in state.skipped:
                    state.skipped.add(rel)
                    ports.log.note(f"screenshot {rel} skipped: {why}")
                continue
            out.append(rel)
        return out

    def stage_visual(self, st: StageData):
        ports = self.ports
        vp = self.visual_cfg()
        return bool(vp) and visual_hit(vp, list(st.get("files") or []) + ports.checkout.changed_paths())

    def shot_methods(self):
        """{method: entry} from engine.shot_table, read from the base branch (a worker can edit the working copy, not that);
        {} when unset or unreadable (then a visual stage works the old way)."""
        facts, ports, state = self.facts, self.ports, self.state
        if state.shot_cache is None:
            state.shot_cache = dict[str, Any]()
            rel = (facts.cfg.shot_table or "").strip()
            if rel:
                try:
                    text = self.git.show(facts.wt, facts.cfg.base, rel).strip()
                except SlotGitError:
                    text = ""
                methods, err = looks.parse_table(text) if text else ({}, f"{rel} is not on {facts.cfg.base}")
                if err:
                    ports.warn(f"engine.shot_table: {err}; visual stages work the old way")
                state.shot_cache = methods
        return state.shot_cache

    def shot_table(self):
        """The shot methods the repo can render, as the planner and the writer are told them."""
        return looks.table_text(self.shot_methods())

    def look_ready(self, st: StageData):
        return bool(self.shot_methods()) and self.stage_visual(st)

    def show_pictures(self) -> list[tuple[str, ArtifactMeta]]:
        """The run's pictures the owner may want to see (role before, after or result), oldest first, each with its address
        `artifact:<repo>/<bead>/<run>/<stage>-<attempt>/<name>`: the store is the one record, so a crash after the land loses none."""
        facts, ports = self.facts, self.ports
        repo = ports.ports.repo.key()
        slot = ArtifactSlot(repo=repo, bead=facts.bead, run=facts.run_id, stage="", attempt=0)
        return [(f"artifact:{repo}/{facts.bead}/{facts.run_id}/{f.parent.name}/{m.name}", m)
                for f, m in store.run_listing(facts.home.artifact_store(), slot) if m.kind in IMAGE_KINDS and m.role != "progress"]

    def before_pictures(self) -> list[tuple[Path, ArtifactMeta]]:
        """The pictures the worker registered with role `before` in this run: the worker says what is a before, nothing is matched."""
        hand, facts = self.hand, self.facts
        if not hand.artifact_repo:
            return []
        slot = ArtifactSlot(repo=hand.artifact_repo, bead=facts.bead, run=facts.run_id, stage="", attempt=0)
        return [(f, m) for f, m in store.run_listing(facts.home.artifact_store(), slot) if m.role == "before" and m.kind in IMAGE_KINDS]

    def render_shots(self, reqs: Any, rnd: Any) -> tuple[list[str], list[str]]:
        """([picture names under the evidence dir], [errors]): the requested shot methods run by the engine, outside any lane's
        sandbox, each built only from the project's table (looks.build). Full-size copies go to the evidence dir; the judge's
        shrunk ones to <run>/looks/r<rnd>/."""
        hand, facts, ports, state = self.hand, self.facts, self.ports, self.state
        base = facts.run_dir / "looks" / f"r{rnd}"
        names: list[str] = []
        errs: list[str] = []
        asked = list(reqs[:looks.MAX_REQUESTS])
        state.last_reqs = list(asked)
        ports.steps.begin("render", f"render shots, round {rnd}", round=rnd)
        for k, req in enumerate(asked):
            files, m, err = self.render_one(req, rnd, k, base)
            if err:
                errs.append(err)
            for f in files:
                names.append(self.keep_picture(f, names, base, rnd))
            if m and files:
                self.warn_if_untracked(m, files)
        state.rendered = sorted({*state.rendered, *names})
        if names:
            hand.render_stale = False  # the pictures show the tree again
        plural = "" if len(names) == 1 else "s"
        bad = f", {len(errs)} error{'' if len(errs) == 1 else 's'}" if errs else ""
        ports.steps.outcome("rendered" if names else "failed", f"{len(names)} picture{plural}{bad}")
        return names, errs

    def render_one(self, req: Any, rnd: Any, k: int, base: Path) -> tuple[list[Path], Any, str]:
        """One requested shot method run: (the files it made, its table entry, why not)."""
        facts, ports = self.facts, self.ports
        out_dir = base / "raw" / f"{k}-{safe_name(str(req.get('method') or '?'))}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd, m, err = looks.build(self.shot_methods(), req, out_dir)
        if err or m is None:
            return [], None, err
        before = looks.snapshot(m, facts.wt)
        rc, tail = ports.sh(cmd, timeout=m["timeout_min"] * 60, save=facts.run_dir / "looks" / f"r{rnd}-{k}-{m['method']}.log")
        files = looks.collect(m, facts.wt, out_dir, before) if rc == 0 else []  # a failed run's files are no render
        if not files:
            what = f"failed (exit {rc})" if rc else "made no pictures"
            return [], m, f"shot method {m['method']} {what}: {tail.strip()[-300:] or 'no output'}"
        return files, m, ""

    def warn_if_untracked(self, m: Any, files: list[Path]) -> None:
        facts, ports = self.facts, self.ports
        inside = [f for f in files if str(f).startswith(str(Path(facts.wt)) + os.sep)]
        if inside and not self.git.check_ignore(facts.wt, [str(inside[0])]):
            ports.warn(f"shot method {m['method']} writes pictures in the worktree ({m['out'] or inside[0].parent}) and that folder is not "
                   "ignored by git: they will show up as unexplained new files; add it to .gitignore")

    def keep_picture(self, f: Path, names: list[str], base: Path, rnd: int) -> str:
        """The full-size copy goes to the evidence dir and is registered in the artifact store (stage look, attempt = the round, role
        result), the judge's shrunk one beside the round; one name per picture within a round."""
        facts = self.facts
        name, j = f.name, 1
        while name in names:
            name, j = f"{j}-{f.name}", j + 1
        facts.evidence_dir.mkdir(parents=True, exist_ok=True)
        if not self.keeper().keep(f, facts.evidence_dir / name):
            self.note_dropped()
        self.register(f, name, rnd)
        looks.downscale(f, base / name, facts.cfg.look_max_px)
        return name

    def register(self, f: Path, name: str, rnd: int) -> None:
        """The engine's render joins the artifact store through the one writer; a refusal is a warning (a picture is never worth a run)."""
        facts, ports = self.facts, self.ports
        try:
            slot = ArtifactSlot(repo=ports.ports.repo.key(), bead=facts.bead, run=facts.run_id, stage="look", attempt=rnd)
            store.add(facts.home.artifact_store(), slot, f, name=name, caption=f"engine render, round {rnd}",
                      role="result", now=ports.now(), cap=int(facts.cfg.evidence_cap_mb) << 20)
        except (Refused, OSError) as err:
            ports.warn(f"render {name} not registered as an artifact: {err}")

    def persist_look(self):
        """What the owner-look bead needs goes into the checkpoint, so a crash after the land still files it."""
        ports = self.ports
        ports.checkpoints.keep_look()

    def keep_evidence(self) -> list[Path]:
        """Pictures the writer saved as proof outlive the worktree: copied to the run dir, named on the bead."""
        facts = self.facts
        kept: list[Path] = []
        if not facts.evidence_dir.is_dir():
            return kept
        out = facts.run_dir / "evidence"
        for f in sorted(facts.evidence_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                dst = out / f.relative_to(facts.evidence_dir)
                if self.keeper().keep(f, dst):
                    kept.append(dst)
        self.note_dropped()
        return kept
