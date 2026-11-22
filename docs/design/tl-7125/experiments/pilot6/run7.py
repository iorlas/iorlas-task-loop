import json, os, random, shutil, signal, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
P = "/tmp/aa/pilot6"
ENG = "/home/iorlas/Workspaces/iorlas-task-loop-b83c5d9a3f13cb9d/ab-engine6"
PY = ENG + "/.venv/bin/python"
BASE = open(P + "/base-commit.txt").read().strip()
WF = {"a": "default", "b": "attempt-budget"}
TASKS = sys.argv[1].split(",")          # e.g. tl-p5a,tl-p5b
MAX_WALL, MAX_TOKENS = 45 * 60, 4_000_000
os.environ["MISE_TRUSTED_CONFIG_PATHS"] = P + ":/tmp/aa/pilot5"
lock = threading.Lock(); consecutive_infra = 0; stop_all = False

def sample():
    mem = {l.split(':')[0]: int(l.split()[1]) for l in open('/proc/meminfo') if l.split(':')[0] in ('MemAvailable',)}
    return {"t": time.time(), "load": open('/proc/loadavg').read().split()[:3], "mem_avail_mb": mem['MemAvailable'] // 1024}

def log(msg):
    with lock:
        with open(P + "/log.txt", "a") as f: f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

def sh(args, cwd=None, check=True, **kw):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)
    if check and r.returncode: raise RuntimeError(f"{args[:4]} rc={r.returncode}: {r.stderr[-400:]}")
    return r

def tl(rd, *args, check=True):
    return sh([PY, "-I", "-m", "taskloop", "--config", rd + "/cfg.toml", *args], cwd=ENG, check=check)

def build(rd, task):
    shutil.rmtree(rd, ignore_errors=True)
    for d in ("state", "slots/aa", "tracker"): os.makedirs(f"{rd}/{d}")
    open(rd + "/cfg.toml", "w").write(f'slot_count = 1\nround_seconds = 15\nslots_root = "{rd}/slots"\n')
    sh(["git", "clone", "-q", "--bare", P + "/base-src", rd + "/aa.git"])
    sh(["git", "clone", "-q", rd + "/aa.git", rd + "/aa-repo"])
    for k, v in (("user.name", "aa"), ("user.email", "aa@example.com")): sh(["git", "-C", rd + "/aa-repo", "config", k, v])
    sh(["git", "-C", rd + "/aa-repo", "worktree", "add", "-q", "--detach", rd + "/slots/aa/s1"])
    sh(["git", "init", "-q"], cwd=rd + "/tracker")
    sh(["bd", "init", "--prefix", "tl", "--non-interactive", "--quiet"], cwd=rd + "/tracker")
    title = open(f"{P}/tasks/{task}.title").read().strip()
    sh(["bd", "create", "--id", task, "--title", title, "--type", "task", "--priority", "2", "--labels", "aa-real",
        "--description", open(f"{P}/tasks/{task}.txt").read()], cwd=rd + "/tracker")
    tl(rd, "slot", "adopt", rd + "/aa-repo", "--db", rd + "/state/factory.db", "--slots-root", rd + "/slots", "--slot-count", "1")

def rows(rd):
    r = tl(rd, "attempt", "list", "--db", rd + "/state/factory.db", "--json", check=False)
    try: return json.loads(r.stdout)["attempts"]
    except Exception: return []

def export(rd):
    ex = tl(rd, "attempt", "export", "--db", rd + "/state/factory.db", "--json", check=False)
    try: return json.loads(ex.stdout)
    except Exception: return None

def run_one(task, arm, group, inflight):
    global consecutive_infra, stop_all
    name = f"{task}_{arm}"; rd = f"{P}/runs/{name}"
    if stop_all: log(f"{name} SKIPPED (stop)"); return
    t0 = time.time(); log(f"{name} start workflow={WF[arm]}")
    res = {"run": name, "task": task, "arm": arm, "workflow": WF[arm], "started": t0, "outcome": None, "states": [],
           "group": group, "inflight_planned": inflight, "sample_start": sample()}
    proc = None
    try:
        build(rd, task)
        out = open(rd + "/rounds.out", "w")
        proc = subprocess.Popen([PY, "-I", "-m", "taskloop", "--config", rd + "/cfg.toml", "rounds", "start", "--no-dashboard",
            "--round-seconds", "15", "--backlog", "aa", "--tracker-root", rd + "/tracker", "--checkout", rd + "/aa-repo",
            "--label", "aa-real", "--max-running", "1", "--minutes", "40", "--db", rd + "/state/factory.db",
            "--artifacts", rd + "/state/artifacts", "--workflow", WF[arm]], cwd=ENG, stdout=out, stderr=subprocess.STDOUT)
        res["rounds_pid"] = proc.pid
        last = None; tick = 0
        while True:
            time.sleep(10); tick += 1
            rs = rows(rd)
            if time.time() - t0 > MAX_WALL and rs and (rs[-1].get("status") != "checking" or time.time() - t0 > MAX_WALL + 900):
                res["outcome"] = "cap:wall"; break
            if not rs:
                if proc.poll() is not None: res["outcome"] = "infra:rounds_exited"; break
                continue
            l = rs[-1]
            st = (l.get("step"), l.get("number"), l.get("status"), l.get("next"), bool(l.get("hold")))
            if st != last: last = st; res["states"].append([round(time.time() - t0), *st]); log(f"{name} {st}")
            if tick % 3 == 0:
                ex = export(rd) or []
                if sum(e.get("t_in") or 0 for e in ex) > MAX_TOKENS: res["outcome"] = "cap:tokens"; stop_all = True; break
            if l.get("status") == "waiting_for_land": res["outcome"] = "pass"; break
            if l.get("hold"): res["outcome"] = "held"; break
            if proc.poll() is not None: res["outcome"] = "infra:rounds_exited"; break
    except Exception as e:
        res["outcome"] = f"infra:{str(e)[:200]}"
    finally:
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try: proc.wait(30)
            except Exception: pass
        res["ended"] = time.time(); res["sample_end"] = sample()
        res["export"] = export(rd); 
        try:
            os.makedirs(P + "/diffs", exist_ok=True)
            slot = rd + "/slots/aa/s1"
            d = sh(["git", "-C", slot, "diff", BASE, "HEAD"], check=False).stdout
            open(f"{P}/diffs/{name}.patch", "w").write(d)
            res["diffstat"] = sh(["git", "-C", slot, "diff", "--numstat", BASE, "HEAD"], check=False).stdout
            res["dirty"] = sh(["git", "-C", slot, "status", "--short"], check=False).stdout
        except Exception as e: res["diff_error"] = str(e)[:200]
        json.dump(res, open(f"{P}/results/{name}.json", "w"), indent=1)
        log(f"{name} END {res['outcome']} {round(res['ended'] - t0)}s")
        with lock:
            if str(res["outcome"]).startswith("infra"):
                consecutive_infra += 1
                if consecutive_infra >= 3: stop_all = True; open(P + "/STOPPED", "w").write("3 consecutive infra failures")
            else: consecutive_infra = 0

if __name__ == "__main__":
    os.makedirs(P + "/results", exist_ok=True); os.makedirs(P + "/runs", exist_ok=True)
    rnd = random.Random(int(time.time()))
    order = TASKS[:]; rnd.shuffle(order)
    lines = []
    groups = []
    for t in order:
        pair = [("a", t), ("b", t)]; rnd.shuffle(pair); groups.append(pair)
        lines.append(f"{t}: " + " ".join(f"{a}({WF[a]})" for a, _ in pair))
    open(P + "/order.txt", "a").write("\n".join(lines) + "\n")
    for g, members in enumerate(groups, 1):
        if stop_all: break
        with ThreadPoolExecutor(2) as ex:
            futs = [ex.submit(run_one, t, a, g, 2) for a, t in members]
            for f in futs: f.result()
