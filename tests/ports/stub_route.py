"""A route.py stand-in for the Delegate contract suite (a plain python script, no shell). $STUB_SCRIPT names a JSON file:
{"contract": 3, "answer": {...} | null, "raw": "text printed instead of the answer", "live": [event dicts], "sleep": secs}.
Every `run` appends {"argv", "brief", "schema"} to <script>.calls and writes the live file ($DELEGATE_LIVE_FILE)."""
import json
import os
import sys
import time


def opt(args, flag):
    return args[args.index(flag) + 1] if flag in args else ""


def main(argv):
    script_path = os.environ["STUB_SCRIPT"]
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    if argv[0] == "contract":
        print(json.dumps({"contract": script.get("contract", 3)}))
        return 0
    with open(opt(argv, "--brief"), encoding="utf-8") as f:
        brief = f.read()
    with open(opt(argv, "--schema"), encoding="utf-8") as f:
        schema = json.load(f)
    with open(script_path + ".calls", "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "brief": brief, "schema": schema}) + "\n")
    live = os.environ.get("DELEGATE_LIVE_FILE")
    if live:
        with open(live, "a", encoding="utf-8") as f:
            f.write(json.dumps({"v": 1, "pid": os.getpid(), "pgid": os.getpgrp(), "run_id": "stub"}) + "\n")
            for ev in script.get("live", []):
                f.write(json.dumps(ev) + "\n")
    time.sleep(script.get("sleep", 0))
    if "raw" in script:
        print(script["raw"])
    elif script.get("answer") is not None:
        print(json.dumps(script["answer"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
