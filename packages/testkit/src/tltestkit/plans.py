"""The engine tests' plain data: the plan, write and review answers, the bead and the procsim check names; no engine, no git."""
from typing import Any

from tlkernel.plancheck import adhoc

HAS_F = "has-f"  # a procsim fake: exit 0 iff f.txt exists in the check's directory


FALSE = "false"  # a procsim fake: exit 1


RED_ONCE = "green-on-d3"  # a procsim fake (registered in setup_method): exit 0 iff f.txt reads d3, red until the writer wrote it


PLAN: dict[str, Any] = {
    "summary": "do it",
    "stages": [
        {
            "goal": "add f",
            "files": ["f.txt"],
            "checks": [adhoc(HAS_F)],
            "hard": False,
            "anchors": [{"path": "f.txt", "lines": "1", "symbol": "", "why": "the file"}],
        }
    ],
    "risks": [],
    "question": "",
    "options": [],
    "decided": "",
    "cases": [{"criterion": "f.txt is shown", "check": None, "class": "show", "shows": []}],  # a visual bead: verify runs
    "leftovers": [],
}


WRITE = {
    "summary": "wrote f",
    "run_checks": [], "checks_run": [{"cmd": "test -f f.txt", "exit": 0}],
    "question": "",
    "options": [],
    "decided": "",
    "bad_checks": [],
    "new_cases": [],
    "unchecked": [],
    "logic_only": "",
}


ROUTE = "/h/.claude/plugins/cache/iorlas-marketplace/iorlas-delegate/%s/skills/delegate/route.py"


CLEAN = {
    "findings": [],
    "unmet": [],
    "criteria": [],
    "question": "",
    "options": [],
    "decided": "",
    "leftovers": [],
    "unchecked": [],
    "look": "",
}


BEAD = {"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists", "labels": ["visual"]}  # visual: verify runs


def review(unmet=(), findings=(), question="", decided=""):
    return dict(CLEAN, unmet=list(unmet), findings=list(findings), question=question, decided=decided)


def verdict(n, v, evidence="", why="", kind="other", source=""):
    return {"n": n, "verdict": v, "evidence": evidence, "why": why, "kind": kind, "source": source}


STILL_OPEN = {"items": [verdict(1, "open", why="only the owner can open it")]}


CAT_ENV = {"kind": "policy", "tool": "shell", "path": ".env", "input": {"command": "cat .env"}}


def finding(severity):
    return {"file": "f.txt", "line": 1, "severity": severity, "fix": f"a {severity} fix", "axis": "standards", "category": "logic",
            "scenario": "input x gives y" if severity == "high" else ""}
