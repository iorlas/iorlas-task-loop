"""The owner-look gallery: taste items the engine filed into owner-look beads (metadata `looks`), with their before and
after pictures, and the owner's two answers: "good" (the item is settled) and "redo" with a note (a follow-up bead carries
the note and the pictures). Every answer can be taken back. Python 3.8+, standard library only.

An item: {id "<source bead>#<n>", look_bead, bead, title, note, shots [{path, role before|after, label}], status
open|good|redo, redo_bead, answer_note, answered}. A look bead from before `looks` existed has no metadata: its
description's "- path" lines become one item per "## <bead>: <title>" section, every picture an "after"."""

import calendar
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

LABEL = "owner-look"
PICTURES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
REFS = ("HEAD", "origin/main", "main", "master")   # where a landed picture may be read when the checkout moved on
NOTE_MAX = 2000


def bd(repo, *args, timeout=30):
    exe = shutil.which("bd")
    if not exe:
        raise OSError("bd is not installed")
    return subprocess.run([exe, *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def bd_json(repo, *args):
    try:
        r = bd(repo, *args, "--json")
        out = json.loads(r.stdout) if r.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None
    return out[0] if isinstance(out, list) and out and args[0] == "show" else out


def _clean(e, look_bead):
    shots = [{"path": str(s.get("path") or ""), "role": "before" if s.get("role") == "before" else "after",
              "label": str(s.get("label") or "")} for s in e.get("shots") or [] if isinstance(s, dict) and s.get("path")]
    return {"id": str(e.get("id") or ""), "look_bead": look_bead, "bead": str(e.get("bead") or ""),
            "title": str(e.get("title") or ""), "note": str(e.get("note") or ""), "shots": shots,
            "status": e.get("status") if e.get("status") in ("good", "redo") else "open",
            "redo_bead": str(e.get("redo_bead") or ""), "answer_note": str(e.get("answer_note") or ""),
            "answered": e.get("answered") or 0}


def parse_description(desc, look_bead):
    """Old look beads: '## bead: title' sections; the '- path' lines of a section are its pictures (all 'after')."""
    items = []
    for sec in re.split(r"\n\n(?=## )", str(desc or "").strip()):
        m = re.match(r"## ([^:\n]+): ([^\n]*)", sec)
        if not m:
            continue
        paths = [p.strip() for p in re.findall(r"^- (\S+\.(?:png|jpe?g|gif|webp))\s*$", sec, re.M | re.I)]
        if paths:
            items.append(_clean({"id": "%s#0" % m.group(1), "bead": m.group(1), "title": m.group(2),
                                 "shots": [{"path": p, "role": "after", "label": Path(p).stem} for p in paths]}, look_bead))
    return items


def items_of(look_bead, shown):
    """Items of one owner-look bead as `bd show` gave it; metadata `looks` wins, the description is the fallback."""
    looks = (shown.get("metadata") or {}).get("looks")
    if isinstance(looks, list):
        return [_clean(e, look_bead) for e in looks if isinstance(e, dict) and e.get("id")]
    return parse_description(shown.get("description"), look_bead)


def epoch(s):
    """An ISO time from bd (UTC when it ends in Z or +00:00) as epoch seconds; 0 when it is not one."""
    s = str(s or "")
    try:
        t = time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0
    return calendar.timegm(t) if s[19:].startswith(("Z", "+00", ".")) or not s[19:] else time.mktime(t)


def collect(repo, beads):
    """Every item of every owner-look bead of the repo (open or closed: an answered item stays so it can be taken back)."""
    out = []
    for b in beads or []:
        if LABEL not in (b.get("labels") or []):
            continue
        shown = bd_json(repo, "show", b["id"]) or {}
        filed = epoch(b.get("created_at") or shown.get("created_at"))
        out += [dict(i, filed=filed) for i in items_of(b["id"], dict(shown, title=shown.get("title") or b.get("title")))]
    return out


def summary(items):
    return {"open": sum(1 for i in items if i["status"] == "open"), "good": sum(1 for i in items if i["status"] == "good"),
            "redo": sum(1 for i in items if i["status"] == "redo")}


def picture(repo, rel, items):
    """(bytes, content-type) of a picture an item names, or None. The path must be one a looks item lists (never a path of
    the caller's choosing), stay inside the repo, and be a picture: disk first, then the base branch's copy."""
    rel = str(rel or "").replace("\\", "/")
    ext = os.path.splitext(rel)[1].lower()
    if ext not in PICTURES or not any(s["path"] == rel for i in items for s in i["shots"]):
        return None
    root = os.path.realpath(repo)
    f = os.path.realpath(os.path.join(root, rel))
    data = None
    if f.startswith(root + os.sep) and os.path.isfile(f):
        try:
            data = Path(f).read_bytes()
        except OSError:
            data = None
    if data is None:
        for ref in REFS:
            try:
                r = subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=repo, capture_output=True, timeout=20)
            except (subprocess.SubprocessError, OSError):
                return None
            if r.returncode == 0:
                data = r.stdout
                break
    if not data or data.startswith(b"version https://git-lfs"):   # an LFS pointer is not a picture
        return None
    return data, PICTURES.get(ext) or mimetypes.guess_type(rel)[0] or "application/octet-stream"


def _save(repo, look_bead, shown, items_meta):
    meta = dict(shown.get("metadata") or {})
    meta["looks"] = items_meta
    r = bd(repo, "update", look_bead, "--metadata", json.dumps(meta))
    return r.returncode == 0, ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1][:200]


def _stored(look_bead, shown):
    """The items to write back: metadata `looks` as is, or the parsed description made into metadata the first time."""
    looks = (shown.get("metadata") or {}).get("looks")
    if isinstance(looks, list):
        return [e for e in looks if isinstance(e, dict)]
    return [{k: v for k, v in i.items() if k != "look_bead"} for i in parse_description(shown.get("description"), look_bead)]


def answer(repo, body, now=None):
    """body: {look_bead, item, verdict good|redo|undo, note}. good: the item is settled, and the look bead closes when no
    item waits. redo: a follow-up bead carries the note and the pictures. undo: back to open (the follow-up is closed,
    a closed look bead is reopened). -> (http code, body). One answer per item; the second to arrive finds it answered."""
    now = now or time.time()
    if not isinstance(body, dict):
        return 400, {"code": "bad_body", "error": "The request was not understood."}
    look_bead, item_id, verdict = body.get("look_bead"), body.get("item"), body.get("verdict")
    note = body.get("note") if isinstance(body.get("note"), str) else ""
    note = note.strip()[:NOTE_MAX]
    if verdict not in ("good", "redo", "undo") or not isinstance(look_bead, str) or not re.match(r"^[A-Za-z0-9][\w.-]*$", look_bead) \
            or not isinstance(item_id, str):
        return 400, {"code": "bad_body", "error": "The request was not understood."}
    if verdict == "redo" and not note:
        return 400, {"code": "empty", "error": "Write what to change first."}
    try:
        shown = bd_json(repo, "show", look_bead)
        if not shown or LABEL not in (shown.get("labels") or []):
            return 404, {"code": "bead_missing", "error": "The look bead %s no longer exists." % look_bead}
        stored = _stored(look_bead, shown)
        e = next((x for x in stored if x.get("id") == item_id), None)
        if e is None:
            return 404, {"code": "item_missing", "error": "That item is gone. Reload the page."}
        state = e.get("status") if e.get("status") in ("good", "redo") else "open"
        if verdict == "undo":
            if state == "open":
                return 200, {"ok": True, "status": "open"}
            if state == "redo" and e.get("redo_bead"):
                bd(repo, "close", e["redo_bead"], "--reason", "the owner took the redo back")
            e.update(status="open", redo_bead="", answer_note="", answered=0)
        elif state != "open":
            return 409, {"code": "answered", "error": "Already answered (%s). Take that back first." % state,
                         "status": state}
        elif verdict == "good":
            e.update(status="good", answer_note=note, answered=now)
        else:
            made = _file_redo(repo, look_bead, e, note)
            if not made[0]:
                return 502, {"code": "bd", "error": "bd refused the follow-up bead: %s" % made[1]}
            e.update(status="redo", redo_bead=made[1], answer_note=note, answered=now)
        ok, why = _save(repo, look_bead, shown, stored)
        if not ok:
            return 502, {"code": "bd", "error": "bd refused the answer: %s" % why}
        waiting = sum(1 for x in stored if x.get("status") not in ("good", "redo"))
        if verdict == "undo" and shown.get("status") == "closed":
            bd(repo, "update", look_bead, "--status", "open")
        elif verdict != "undo" and not waiting:
            bd(repo, "close", look_bead, "--reason", "the owner answered every look")
        return 200, {"ok": True, "status": e["status"], "redo_bead": e.get("redo_bead") or "", "open": waiting}
    except OSError as err:
        return 502, {"code": "no_bd", "error": "The dashboard cannot run bd (%s). Nothing was changed." % err}
    except subprocess.SubprocessError as err:
        return 502, {"code": "bd", "error": "bd did not answer (%s)." % type(err).__name__}


def _file_redo(repo, look_bead, e, note):
    """The follow-up bead of a redo: the owner's note and the pictures, related to the bead the look came from."""
    pics = "\n".join("- %s (%s)" % (s["path"], s.get("role") or "after") for s in e.get("shots") or [])
    desc = "The owner looked at \"%s\" (%s) and asked for a change.\n\nWhat to change:\n%s\n\nPictures:\n%s\n" % (
        e.get("title") or e.get("id"), e.get("bead") or look_bead, note, pics or "(none)")
    args = ["create", "Redo look: " + (e.get("title") or e.get("id") or look_bead)[:90], "--type", "task", "--priority", "2",
            "--description", desc, "--deps", "related:" + (e.get("bead") or look_bead), "--json"]
    r = bd(repo, *args)
    if r.returncode != 0:
        return False, ((r.stderr or r.stdout or "").strip().splitlines() or ["no output"])[-1][:200]
    try:
        out = json.loads(r.stdout or "{}")
        out = out[0] if isinstance(out, list) and out else out
        made = str(out.get("id") or "")
    except (ValueError, AttributeError):
        made = ""
    if not made:
        return False, "bd's answer had no id"
    bd(repo, "update", made, "--metadata", json.dumps({"looks": {"from": e.get("id"), "shots": e.get("shots") or [], "note": note}}))
    return True, made
