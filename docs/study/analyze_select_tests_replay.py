#!/usr/bin/env python3
"""Per-landing analysis of RECORDS.json: why the selector chose what it chose (offline; imports tools/ unmodified).

Output: JSON on stdout with the checker result (as specified), the hub share, the cause of each full-suite
selection, and a labelled counterfactual that drops feature-map modules missing from that landing's inventory.
"""
import json, statistics, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import select_tests as S, replay_select_tests as R

HUBS = ("skills/task-loop/engine.py", "skills/task-loop/tl.py", "skills/task-loop/loop.py")

def main(path):
    d = json.load(open(path))
    feats, edges = S.feature_map(), S.layer_edges()
    full = {k: set(v) for k, v in edges.items()}
    out = []
    for l in d["landings"]:
        inv = l["inventory"]
        disc = {t.split(".", 1)[0] for t in inv}
        assigned = {m for ms in feats.values() for m in ms}
        missing = sorted(assigned - disc)
        full_paths = sorted(p for p in l["paths"] if S.feature_for_path(p, feats) is S.FULL)
        sel = S.select_ids(l["paths"], features=feats, edges=edges, all_ids=inv)
        if len(sel) < len(inv): cause = "selected a subset"
        elif missing: cause = "feature map names modules absent from that inventory"
        elif full_paths: cause = "path forces whole suite"
        else: cause = "mapped, subset equals whole suite"
        # counterfactual: the same HEAD map restricted to modules that existed then
        f2 = {k: [m for m in v if m in disc] for k, v in feats.items()}
        cf = S.select_ids(l["paths"], features=f2, edges=edges, all_ids=inv)
        fails = set(l["failures"]) | set(l["errors"])
        out.append({"id": l["id"], "version": l["version"], "paths": len(l["paths"]),
                    "hub": [p for p in l["paths"] if p in HUBS],
                    "forcing_paths": full_paths[:5], "missing_modules": len(missing),
                    "selected": len(sel), "inventory": len(inv), "share": len(sel) / len(inv),
                    "cause": cause, "cf_selected": len(cf), "cf_share": len(cf) / len(inv),
                    "cf_missed": sorted(fails - set(cf)), "red_ids": len(fails)})
    base = R.replay(R.validate(d["landings"]) if False else d["landings"])
    hub = sum(1 for o in out if o["hub"])
    causes = {}
    for o in out: causes[o["cause"]] = causes.get(o["cause"], 0) + 1
    json.dump({"checker": {"misses": sum(len(x["missed"]) for x in base["landings"]), "ok": base["ok"],
                           "median_share": base["median_share"]},
               "hub_landings": hub, "hub_share": hub / len(out), "causes": causes,
               "counterfactual_median_share": statistics.median(o["cf_share"] for o in out),
               "counterfactual_misses": sum(len(o["cf_missed"]) for o in out),
               "counterfactual_note": "HEAD feature map restricted to modules present in the landing's inventory; NOT the checker's rule",
               "per_landing": out}, sys.stdout, indent=1)

if __name__ == "__main__":
    main(sys.argv[1])
