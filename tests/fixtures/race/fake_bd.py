"""A bd stand-in for the race test: one JSON store under an flock, so concurrent processes see one tracker and `--claim`
is atomic as in bd 1.3 (idempotent for the same actor; refused while another actor holds the bead, even an open one).

State in $FAKE_BD_DIR: store.json, store.lock, calls.jsonl (every call) and claims.jsonl (every hold change of a bead).
"""

import fcntl
from typing import Any
import json
import os
import sys
import time

TTL = 300  # bd's lease, seconds


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def opt(args, flag, default=None) -> Any:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default


def opts(args, flag):
    return [args[i + 1] for i, x in enumerate(args[:-1]) if x == flag]


def secs(text):
    n, unit = int(text[:-1]), text[-1]
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


class Bd:
    def __init__(self, store, actor, log):
        self.s, self.actor, self.log = store, actor, log

    def bead(self, bid):
        return self.s["beads"].get(bid)

    def held(self, b, why, by):
        self.log.append({"t": time.time(), "bead": b["id"], "op": why, "by": by, "actor": self.actor,
                         "tree": os.environ.get("RACE_ACTOR", "")})

    def free(self, b, why):
        if b.get("status") == "in_progress" or b.get("assignee"):
            self.held(b, "release:" + why, b.get("assignee") or "")
        b.update(status="open", assignee="")
        b.pop("lease_expires_at", None)

    def run(self, a):
        cmd = a[0] if a else ""
        if cmd in ("ready", "list"):
            label, status = opt(a, "--label"), opt(a, "--status")
            out = []
            for b in self.s["beads"].values():
                if label and label not in b.get("labels", []):
                    continue
                if cmd == "ready" and b["status"] != "open":
                    continue
                if status and b["status"] != status:
                    continue
                if cmd == "list" and not status and "--all" not in a and b["status"] == "closed":
                    continue
                out.append(b)
            return 0, json.dumps(out)
        if cmd == "show":
            b = self.bead(a[1])
            return (0, json.dumps([b])) if b else (1, "")
        if cmd == "comments":
            if a[1] == "add":
                b = self.bead(a[2])
                b.setdefault("comments", []).append({"author": self.actor, "text": a[3], "created_at": stamp(time.time())})
                return 0, ""
            b = self.bead(a[1])
            return 0, json.dumps((b or {}).get("comments", []))
        if cmd == "update":
            b = self.bead(a[1])
            if not b:
                return 1, ""
            if "--claim" in a:
                if b["status"] in ("closed", "blocked") or b.get("assignee") not in (None, "", self.actor):
                    return 1, ""
                # every won claim, a re-claim by the same actor too: RACE_ACTOR names the process tree that made it
                self.held(b, "claim" if b["status"] != "in_progress" or b.get("assignee") != self.actor else "reclaim",
                          self.actor)
                b.update(status="in_progress", assignee=self.actor, lease_expires_at=stamp(time.time() + TTL))
            for kv in opts(a, "--set-metadata"):
                k, _, v = kv.partition("=")
                b.setdefault("metadata", {})[k] = v
            for k in opts(a, "--unset-metadata"):
                b.setdefault("metadata", {}).pop(k, None)
            if "--status" in a:
                st = opt(a, "--status")
                if st != "in_progress" and b["status"] == "in_progress":
                    self.held(b, "release:status %s" % st, b.get("assignee") or "")
                    b.pop("lease_expires_at", None)
                b["status"] = st
            if "--assignee" in a:
                if b.get("assignee") and not opt(a, "--assignee") and b["status"] == "in_progress":
                    self.held(b, "release:assignee", b["assignee"])
                b["assignee"] = opt(a, "--assignee")
            if "--append-notes" in a:
                b["notes"] = (b.get("notes", "") + "\n" + opt(a, "--append-notes")).strip()
            return 0, ""
        if cmd == "unclaim":
            b = self.bead(a[1])
            if not b:
                return 1, ""
            self.free(b, "unclaim")
            return 0, ""
        if cmd == "heartbeat":
            b = self.bead(a[1])
            if not b or b["status"] != "in_progress" or b.get("assignee") != self.actor:
                return 1, ""
            b["lease_expires_at"] = stamp(time.time() + TTL)
            return 0, ""
        if cmd == "reclaim":
            cut, who = stamp(time.time() - secs(opt(a, "--older-than", "15m"))), opts(a, "--assignee")
            for b in self.s["beads"].values():
                if (b["status"] == "in_progress" and (not who or b.get("assignee") in who)
                        and (b.get("lease_expires_at") or "") < cut):
                    self.free(b, "reclaim")
            return 0, ""
        if cmd == "close":
            b = self.bead(a[1])
            if not b:
                return 1, ""
            if b["status"] == "in_progress":
                self.held(b, "release:close", b.get("assignee") or "")
            b.update(status="closed", close_reason=opt(a, "--reason", ""))
            b.pop("lease_expires_at", None)
            return 0, ""
        if cmd == "create":
            self.s["n"] = self.s.get("n", 0) + 1
            bid = "new-%d" % self.s["n"]
            self.s["beads"][bid] = {"id": bid, "title": a[1], "status": "open", "priority": int(opt(a, "--priority", "2")),
                                    "issue_type": opt(a, "--type", "task"),
                                    "labels": [x for x in (opt(a, "--labels") or "").split(",") if x]}
            return 0, "Created issue: " + bid
        if cmd == "label" and a[1:2] == ["add"]:
            b = self.bead(a[2])
            if b and a[3] not in b.setdefault("labels", []):
                b["labels"].append(a[3])
            return 0, ""
        return 0, ""  # provenance and the rest: accepted, nothing kept


def main(argv):
    actor = "unknown"
    if argv[:1] == ["--actor"]:
        actor, argv = argv[1], argv[2:]
    d = os.environ["FAKE_BD_DIR"]
    with open(os.path.join(d, "store.lock"), "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        path = os.path.join(d, "store.json")
        with open(path, encoding="utf-8") as f:
            store = json.load(f)
        holds = []
        rc, out = Bd(store, actor, holds).run(argv)
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f)
        os.replace(tmp, path)
        with open(os.path.join(d, "calls.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "actor": actor, "args": argv, "rc": rc, "pid": os.getpid(),
                                "ppid": os.getppid()}) + "\n")
        if holds:
            with open(os.path.join(d, "claims.jsonl"), "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(h) + "\n" for h in holds))
    if out:
        print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
