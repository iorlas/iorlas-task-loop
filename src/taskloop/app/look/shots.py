"""The pictures of a visual change: which stages are visual, the shot methods the repo can render, the engine's own renders,
the writer's evidence, and the copies that land in the repo."""
import fnmatch
import glob
import os
import shutil
from pathlib import Path
from typing import Any

from taskloop.adapters import looks
from taskloop.domain.checks.matchers import glob_re
from taskloop.domain.look.matchers import image_names, safe_name

IMAGE_EXT = (".png", ".jpg", ".jpeg")
MAX_SHOTS, MAX_SHOT_BYTES = 20, 5 * 1024 * 1024


def visual_hit(vp: Any, paths: Any) -> bool:
    """True when a path matches an include glob and no exclude glob."""
    inc = [glob_re(g) for g in vp.include] if vp else []
    exc = [glob_re(g) for g in vp.exclude] if vp else []
    return any(any(r.match(p) for r in inc) and not any(r.match(p) for r in exc) for p in paths)


class Pictures:
    def __init__(self, host: Any) -> None:
        self.e = host

    def visual_cfg(self):
        e = self.e
        vp = e.cfg.visual_paths
        return vp if vp and vp.include else None

    def shots(self) -> list[str]:
        """The pictures the writer saved under the evidence dir, relative to it."""
        e = self.e
        if not e.evidence_dir.is_dir():
            return []
        out: list[str] = []
        for f in sorted(e.evidence_dir.rglob("*")):
            if not (f.is_file() and f.suffix.lower() in IMAGE_EXT):
                continue
            rel = str(f.relative_to(e.evidence_dir))
            if self.shot_methods() and rel not in e.rendered_names:
                continue  # with a shot table the pictures are the engine's own, of this run: never a writer's or an older run's
            why = f"over {MAX_SHOT_BYTES >> 20} MB" if f.stat().st_size > MAX_SHOT_BYTES else (
                f"more than {MAX_SHOTS} screenshots" if len(out) >= MAX_SHOTS else "")
            if why:
                if rel not in e.shots_skipped:
                    e.shots_skipped.add(rel)
                    e.log.note(f"screenshot {rel} skipped: {why}")
                continue
            out.append(rel)
        return out

    def stage_visual(self, st: Any):
        e = self.e
        vp = self.visual_cfg()
        return bool(vp) and visual_hit(vp, list(st.get("files") or []) + e.checkout.changed_paths())

    def shot_methods(self):
        """{method: entry} from engine.shot_table, read from the base branch (a worker can edit the working copy, not that);
        {} when unset or unreadable (then a visual stage works the old way)."""
        e = self.e
        if e.shot_cache is None:
            e.shot_cache = dict[str, Any]()
            rel = (e.cfg.shot_table or "").strip()
            if rel:
                text = e.git("show", f"{e.cfg.base}:{rel}")
                methods, err = looks.parse_table(text) if text else ({}, f"{rel} is not on {e.cfg.base}")
                if err:
                    e.warn(f"engine.shot_table: {err}; visual stages work the old way")
                e.shot_cache = methods
        return e.shot_cache

    def shot_table(self):
        """The shot methods the repo can render, as the planner and the writer are told them."""
        return looks.table_text(self.shot_methods())

    def look_ready(self, st: Any):
        return bool(self.shot_methods()) and self.stage_visual(st)

    def references_text(self):
        """What the planner is told the task already has to look at: image files its text names, and the last landed shots."""
        e = self.e
        found = []
        for rel in image_names(e.briefs.text()):
            if (Path(e.wt) / rel).is_file():
                found.append(rel)
        dest = (e.cfg.evidence_dir or "").strip("/")
        before = sorted(Path(e.wt, dest).glob("*/*.png"))[-6:] if dest and Path(e.wt, dest).is_dir() else []
        if not (found or before):
            return ("No reference image is in the task or under the repo's look reviews. If the task does not say what it should "
                    "look like (a mockup, a target, a screen to match), plan from the bead text and assume the look; "
                    "say the assumption in the summary.")
        return f"Reference images the task has: {', '.join(found + [str(b.relative_to(e.wt)) for b in before])}."

    def before_shot(self, name: Any):
        """A landed picture of the same screen (same file name under evidence_dir, another bead's folder): the newest."""
        e = self.e
        dest = (e.cfg.evidence_dir or "").strip("/")
        if not dest or not Path(e.wt, dest).is_dir():
            return None
        cands = [f for f in Path(e.wt, dest).glob("*/" + glob.escape(name)) if f.parent.name != e.bead]
        return max(cands, key=lambda f: f.stat().st_mtime) if cands else None

    def render_shots(self, reqs: Any, rnd: Any) -> tuple[list[str], list[str]]:
        """([picture names under the evidence dir], [errors]): the requested shot methods run by the engine, outside any lane's
        sandbox, each built only from the project's table (looks.build). Full-size copies go to the evidence dir; the judge's
        shrunk ones to <run>/looks/r<rnd>/."""
        e = self.e
        base = e.run_dir / "looks" / f"r{rnd}"
        names: list[str] = []
        errs: list[str] = []
        asked = list(reqs[:looks.MAX_REQUESTS])
        e.last_reqs = list(asked)
        e.steps.begin("render", f"render shots, round {rnd}", round=rnd)
        for k, req in enumerate(asked):
            files, m, err = self.render_one(req, rnd, k, base)
            if err:
                errs.append(err)
            for f in files:
                names.append(self.keep_picture(f, names, base))
            if m and files:
                self.warn_if_untracked(m, files)
        e.rendered_names |= set(names)
        if names:
            e.render_stale = False
        plural = "" if len(names) == 1 else "s"
        bad = f", {len(errs)} error{'' if len(errs) == 1 else 's'}" if errs else ""
        e.steps.outcome("rendered" if names else "failed", f"{len(names)} picture{plural}{bad}")
        return names, errs

    def render_one(self, req: Any, rnd: Any, k: int, base: Path) -> tuple[list[Path], Any, str]:
        """One requested shot method run: (the files it made, its table entry, why not)."""
        e = self.e
        out_dir = base / "raw" / f"{k}-{safe_name(str(req.get('method') or '?'))}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd, m, err = looks.build(self.shot_methods(), req, out_dir)
        if err or m is None:
            return [], None, err
        before = looks.snapshot(m, e.wt)
        rc, tail = e.sh(cmd, timeout=m["timeout_min"] * 60, save=e.run_dir / "looks" / f"r{rnd}-{k}-{m['method']}.log")
        files = looks.collect(m, e.wt, out_dir, before) if rc == 0 else []  # a failed run's files are no render
        if not files:
            what = f"failed (exit {rc})" if rc else "made no pictures"
            return [], m, f"shot method {m['method']} {what}: {tail.strip()[-300:] or 'no output'}"
        return files, m, ""

    def warn_if_untracked(self, m: Any, files: list[Path]) -> None:
        e = self.e
        inside = [f for f in files if str(f).startswith(str(Path(e.wt)) + os.sep)]
        if inside and e.sh(["git", "check-ignore", "-q", str(inside[0])], pin=True)[0] != 0:
            e.warn(f"shot method {m['method']} writes pictures in the worktree ({m['out'] or inside[0].parent}) and that folder is not "
                   "ignored by git: they will show up as unexplained new files; add it to .gitignore")

    def keep_picture(self, f: Path, names: list[str], base: Path) -> str:
        """The full-size copy goes to the evidence dir, the judge's shrunk one beside the round; one name per picture within a round."""
        e = self.e
        name, j = f.name, 1
        while name in names:
            name, j = f"{j}-{f.name}", j + 1
        e.evidence_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, e.evidence_dir / name)
        looks.downscale(f, base / name, int(e.cfg.look_max_px))
        return name

    def lfs_ok(self, shots: Any):
        """False when .gitattributes sends these pictures to LFS and git lfs is not installed."""
        e = self.e
        try:
            rows = (Path(e.wt) / ".gitattributes").read_text(errors="replace").splitlines()
        except OSError:
            return True
        lfs = [r.split()[0] for r in rows if r.split() and not r.startswith("#") and "filter=lfs" in r]
        if not any(fnmatch.fnmatch(Path(sh).name, pat.split("/")[-1]) for sh in shots for pat in lfs):
            return True
        rc, _ = e.sh(["git", "lfs", "version"], pin=True)
        return rc == 0

    def copy_looks(self):
        """The screenshots of a visual change go into the repo (engine.evidence_dir/<bead>/), in the land's commit."""
        e = self.e
        vp, dest = self.visual_cfg(), (e.cfg.evidence_dir or "").strip("/")
        shots = self.shots()
        if not (vp and shots and visual_hit(vp, e.checkout.changed_paths())):
            self.persist_look()
            return
        if not dest:
            e.warn("screenshots saved but engine.evidence_dir is not set: they are not kept in the repo")
            return
        if not self.lfs_ok(shots):
            e.warn("engine.evidence_dir pictures go to git LFS (.gitattributes) but git lfs is not installed: "
                      "no screenshot is copied into the repo")
            return
        e.look_paths = list[str]()
        for s in shots:
            to = Path(e.wt) / dest / e.bead / s
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(e.evidence_dir / s, to)
            e.look_paths.append(f"{dest}/{e.bead}/{s}")
        self.persist_look()

    def persist_look(self):
        """What the owner-look bead needs goes into the checkpoint, so a crash after the land still files it."""
        e = self.e
        e.checkpoints.keep_look()

    def keep_evidence(self) -> list[Path]:
        """Pictures the writer saved as proof outlive the worktree: copied to the run dir, named on the bead."""
        e = self.e
        kept: list[Path] = []
        if not e.evidence_dir.is_dir():
            return kept
        out = e.run_dir / "evidence"
        for f in sorted(e.evidence_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                dst = out / f.relative_to(e.evidence_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                kept.append(dst)
        return kept
