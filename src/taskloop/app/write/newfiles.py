"""The untracked files of a stage: which the plan or the writer meant, which are ignored, which the review must explain,
and where strays go."""
import shutil
from pathlib import Path
from typing import Any

from tlkernel.gitport import Git

from taskloop.app.write.host import NewFilesHost
from taskloop.app.write.review_prompt import NEW_FILES_TEXT
from taskloop.domain.write.newfiles import new_file_kind


class NewFiles:
    def __init__(self, host: NewFilesHost, git: Git) -> None:
        self.e = host
        self.git = git

    STRAY_LINES, STRAY_CHARS = 80, 6000
    STAGE_DIFF_CAP = 40000

    def new_file_kind(self, path: str) -> str:
        e = self.e
        return new_file_kind(path, e.cfg.untracked_ignore or [], e.accepted_new, e.plan_data)

    def new_by_kind(self) -> dict[str, list[str]]:
        e = self.e
        out: dict[str, list[str]] = {"ignored": [], "meant": [], "unexplained": []}
        for p in e.checkout.slot_status()[1]:
            out[self.new_file_kind(p)].append(p)
        return out

    def new_file_view(self, path: str) -> str:
        """tl-bxk.10.24: what the review brief shows of an unexplained new file: its first 80 lines, or "binary, N bytes"."""
        e = self.e
        f = Path(e.wt) / path
        try:
            data = f.read_bytes()
        except OSError:
            return "(unreadable)"
        if b"\0" in data[:8000]:
            return f"binary, {len(data)} bytes"
        lines = data.decode("utf-8", "replace").splitlines()
        text = "\n".join(lines[:self.STRAY_LINES])[:self.STRAY_CHARS]
        more = len(lines) - self.STRAY_LINES
        return text + (f"\n... ({more} more lines)" if more > 0 else "")

    def new_files_brief(self, unexplained: list[str]) -> str:
        return NEW_FILES_TEXT + "".join(f"- {p}\n<content>\n{self.new_file_view(p)}\n</content>\n" for p in unexplained)

    def undecided_new(self, unexplained: list[str], review: Any) -> list[str]:
        """The unexplained files the review neither accepted nor rejected (a .meta follows the file it belongs to)."""
        said = set(review.get("accept_files") or []) | set(review.get("reject_files") or [])
        return [p for p in unexplained if p not in said and not (p.endswith(".meta") and p[:-5] in said)]

    def quarantine_strays(self) -> list[str]:
        """tl-bxk.10.24: before the land gate, every untracked file that is neither meant nor ignored leaves the tree for
        .task/<bead>/evidence/strays/ (kept), so the gate runs on exactly what is committed. Listed in the trace and on the bead."""
        e = self.e
        moved: list[str] = []
        for p in self.new_by_kind()["unexplained"]:
            dst = e.evidence_dir / "strays" / p
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(e.wt) / p), str(dst))
            moved.append(p)
        if moved:
            e.write.strays += [p for p in moved if p not in e.write.strays]
            kept = e.evidence_dir / "strays"
            e.log.note(f"stray untracked files moved out of the tree to {kept}: {', '.join(moved)}")
            e.comment("Land (engine): untracked files no stage or review accepted were left out of the commit and the gate, "
                      f"kept in {kept}: {', '.join(moved)}")
        return moved

    def stage_work(self, unexplained: list[str], ignored: list[str]) -> str:
        """tl-bxk.10.18: the review brief's account of the work: this stage's diff (the tree the stage started from to the
        tree now; the task's base for the first stage), inline up to STAGE_DIFF_CAP chars; over it, the --stat and the
        instruction to read only the changed files plus the plan. Untracked files not meant for the commit are left out."""
        e = self.e
        tree = e.checkout.tree_hash()
        base = e.stage_tree or e.checkout.base_sha()
        if not tree:
            return f"The work: `git diff {base}` and new files."
        skip = unexplained + ignored
        diff = self.git.diff(e.wt, base, tree, exclude=skip)
        if len(diff) <= self.STAGE_DIFF_CAP:
            if not diff:
                return "The work of this stage: no file changed."
            return ("The work of this stage (the diff from where the stage started to now; earlier stages are in the tree "
                    f"but not in this diff):\n<diff>\n{diff if diff.endswith(chr(10)) else diff + chr(10)}</diff>")
        stat = self.git.diff(e.wt, base, tree, exclude=skip, stat=True)
        return (f"The work of this stage is too big to inline ({len(diff)} chars; the cap is {self.STAGE_DIFF_CAP}). Its changed files:\n"
                f"{stat}\nRead only the changed files plus the plan; do not diff the whole task.")
