"""Visual work (tl-bxk.13.15, docs/design/visual-work.md): the project's shot table, the commands the engine builds from a
writer's shot request, downscaling, the look judge's prompt and the comparison that stops a repeated defect.

Pure helpers, no engine state: engine.py runs the commands. Python 3.8+, standard library only.

The rule: the engine renders, a look judge judges, the owner decides taste. A writer never renders: it names shot methods
from the project's table and the engine runs them.

The shot table is a JSON file in the repo (engine.shot_table, read from the base branch, so a worker cannot edit what the
engine runs):

    {"v": 1, "methods": [
      {"method": "CreatorShots",
       "summary": "named creator categories",                     # one line for the writer's prompt
       "argv": ["Unity", "-batchmode", "-projectPath", "client", "-executeMethod", "Lifesim.Editor.CreatorShots.Run", "{args}",
                "-logFile", "client/Logs/creator-shots.log"],           # a program and its arguments: no shell
       "args": [{"name": "shots", "flag": "-shots", "pattern": "[\\\\w=,:-]+", "required": false,
                 "about": "body=body,face=face"}],      # flag "" = a positional argument
       "out": "client/Logs/shots",                                # where the pictures land; {out} in argv = a folder the engine gives
       "files": "*.png",                                          # which of them (fnmatch), default *.png
       "timeout_min": 15}]}

The word `{args}` becomes `<flag>`, `<value>` (two argv words; one for a positional argument) for each argument the writer gave (a
name the table does not list, or a value that does not match the argument's pattern, is refused). `{out}` inside a word becomes the
folder the engine creates. A method with neither placeholder writes to `out` and the engine copies what is new there; arguments
go at the end when there is no `{args}` word.
"""

import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_ARG = r"[\w.=,:@/+][\w.=,:@/+-]{0,199}"   # no space, quote or shell character, and no leading dash (never an option)
MAX_REQUESTS = 6                        # shot requests one write may make
CLASSES = ("test", "look-objective", "taste")


def parse_table(text):
    """({method name: entry}, error): the table's methods, or an error text naming what is wrong. An empty table is an error."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return {}, "shot table is not JSON: %s" % e
    rows = data.get("methods") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}, "shot table has no methods"
    out = {}
    for r in rows:
        if not isinstance(r, dict) or not str(r.get("method") or "").strip() or not isinstance(r.get("argv"), list) or not r["argv"] \
                or not all(isinstance(x, str) for x in r["argv"]):
            return {}, "shot table: every method needs a name and an argv list (a program and its arguments, no shell string)"
        try:
            timeout = float(r.get("timeout_min") or 15)
        except (TypeError, ValueError):
            return {}, "shot table: method %s has a timeout_min that is not a number" % r["method"]
        args = []
        for a in r.get("args") or []:
            if not isinstance(a, dict) or not a.get("name") or "flag" not in a:  # flag "" = a positional argument
                return {}, "shot table: method %s has an argument without a name and a flag (flag \"\" is positional)" % r["method"]
            pat = str(a.get("pattern") or DEFAULT_ARG)
            try:
                re.compile(pat)
            except re.error as e:
                return {}, "shot table: argument %s of %s has a bad pattern: %s" % (a["name"], r["method"], e)
            args.append({"name": str(a["name"]), "flag": str(a["flag"]), "pattern": pat,
                         "required": bool(a.get("required")), "about": str(a.get("about") or "")})
        out[str(r["method"]).strip()] = {
            "method": str(r["method"]).strip(), "summary": str(r.get("summary") or "").strip(), "argv": list(r["argv"]),
            "args": args, "out": str(r.get("out") or "").strip("/"), "files": str(r.get("files") or "*.png"),
            "timeout_min": timeout}
    return out, ""


def short(summary, n=150):
    """What a method covers, in the first sentence of its summary, at most n characters."""
    first = re.split(r"(?<=\.)\s", " ".join(str(summary).split()), 1)[0]
    return first if len(first) <= n else first[:n - 3].rstrip() + "..."


def table_text(methods, cap=1800):
    """The menu of shot methods: each method, what it covers (a short line), the arguments it takes."""
    lines = []
    for m in methods.values():
        args = "; ".join("%s%s%s" % (a["name"], " (required)" if a["required"] else "", (" e.g. " + short(a["about"], 70)) if a["about"] else "")
                         for a in m["args"])
        lines.append("- %s: %s%s" % (m["method"], short(m["summary"]) or "(no summary)", (" [args: %s]" % args) if args else ""))
    text = "\n".join(lines)
    return text if len(text) <= cap else text[:cap - 3] + "..."


def build(methods, req, out_dir):
    """(argv, method entry, error) for a writer's request {method, args: [{name, value}], names}. The argv is built only
    from the table's argv with its declared arguments filled in; no shell runs it."""
    m = methods.get(str(req.get("method") or "").strip())
    if not m:
        return [], None, "no shot method %r in the project's table (it has: %s)" % (req.get("method"), ", ".join(methods) or "none")
    given, parts = {}, []
    for a in req.get("args") or []:
        if isinstance(a, dict) and a.get("name"):
            given[str(a["name"])] = str(a.get("value") if a.get("value") is not None else "")
    known = {a["name"]: a for a in m["args"]}
    for name in given:
        if name not in known:
            return [], m, "shot method %s takes no argument %r (it takes: %s)" % (m["method"], name, ", ".join(known) or "none")
    for a in m["args"]:
        v = given.get(a["name"], "")
        if not v.strip():
            if a["required"]:
                return [], m, "shot method %s needs the argument %s" % (m["method"], a["name"])
            continue
        if v.startswith("-") or not re.fullmatch(a["pattern"], v):
            return [], m, "argument %s of %s does not match %s: %r" % (a["name"], m["method"], a["pattern"], v[:80])
        parts += [a["flag"], v] if a["flag"] else [v]
    argv = []
    for w in m["argv"]:
        argv += parts if w == "{args}" else [w.replace("{out}", str(out_dir))]
    return (argv if "{args}" in m["argv"] else argv + parts), m, ""


def snapshot(m, wt):
    """{path: (mtime, size)} of the method's own `out` folder before it runs: only what changes after is its picture."""
    snap = {}
    folder = Path(wt) / m["out"] if m["out"] else None
    if folder and folder.is_dir():
        for f in folder.rglob("*"):
            if f.is_file() and not f.is_symlink():
                st = f.stat()
                snap[f] = (st.st_mtime, st.st_size)
    return snap


def collect(m, wt, out_dir, before=None):
    """The pictures a method made: files matching its `files` in the folder the engine gave it (when argv has {out}), or new or
    changed since `before` (snapshot) in its `out` folder (repo-relative). Never a symlink. Sorted."""
    before = before or {}
    found = []
    for folder, own in ((Path(out_dir), True), (Path(wt) / m["out"] if m["out"] else None, False)):
        if not folder or not folder.is_dir():
            continue
        for f in sorted(folder.rglob("*")):
            if not f.is_file() or f.is_symlink() or not fnmatch.fnmatch(f.name, m["files"]):
                continue
            st = f.stat()
            if own or before.get(f) != (st.st_mtime, st.st_size):
                found.append(f)
    return list(dict.fromkeys(found))


def downscale(src, dst, px):
    """Copy `src` to `dst`, no side longer than `px` when a tool is there to shrink it (sips on macOS, ImageMagick); else a plain
    copy. Returns "" on success or why it was a plain copy."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    tool = shutil.which("sips")
    if tool:
        cmd = [tool, "-Z", str(int(px)), str(src), "--out", str(dst)]
    else:
        tool = shutil.which("magick") or shutil.which("convert")
        cmd = [tool, str(src), "-resize", "%dx%d>" % (int(px), int(px)), str(dst)] if tool else None
    if cmd:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            if r.returncode == 0 and Path(dst).is_file():
                return ""
        except (OSError, subprocess.SubprocessError):
            pass
    shutil.copy2(src, dst)
    return "not downscaled (no sips or ImageMagick, or it failed)"


def words(text):
    return {w for w in re.findall(r"[^\W_]{3,}", str(text).lower())}


def same_defect(a, b):
    """True when two defect descriptions say about the same thing: the same words, or (3+ words each) 60% of the smaller set in the other."""
    x, y = words(a), words(b)
    if not x or not y:
        return False
    if x == y:
        return True
    return min(len(x), len(y)) >= 3 and len(x & y) >= 0.6 * min(len(x), len(y))


def judge_prompt(items, shots, refs, befores, summary=""):
    """The look judge's brief: it has no repo and no task, only the pictures, what must hold, and what the screen should
    look like. Paths are relative to its folder."""
    out = ["You judge how a screen looks from pictures. You have no other context; do not look for any. Do not edit files. "
           "Open every picture below."]
    out.append("\nPictures to judge (rendered by the engine just now):\n" + "".join("- %s\n" % s for s in shots))
    if befores:
        out.append("\nThe same screens before this change:\n" + "".join("- %s (before) <- %s\n" % (b, a) for a, b in befores))
    if refs:
        out.append("\nWhat it should look like (reference images or descriptions):\n" + "".join("- %s\n" % r for r in refs))
    out.append("\nAlways check, for every picture: the screen is there and shows what it should; nothing is clipped, cut off or "
               "overlapping; no error text, magenta or missing texture, empty frame or placeholder; the state asked for is "
               "visible." + ("\nThe change in one line: %s" % summary if summary else ""))
    if items:
        out.append("\nAlso judge each of these (answer one finding per item, the item's text in `item`):\n" +
                   "".join("- %s\n" % i for i in items))
    out.append("\nAnswer findings: per item (and \"general\" for the checks above): verdict pass, or defect with where (which picture, "
               "which part of it) and why in plain words. Judge only what you can see; a matter of taste is never a defect "
               "(give it as pass and say what you saw in why). summary: one paragraph of what you saw.")
    return "".join(out)
