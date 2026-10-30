"""Recorded exchanges: one model call of the engine as it was (the input it sent, the answer the lane returned), replayed as a golden.

A case is a folder tests/fixtures/exchanges/<role>/<case>/ (role: planner, writer, reviewer):
  meta.json    node (plan, write, review); answer and input: "real" (kept from a real run) or "synthetic" (written by hand); source;
               calls: the roles the engine calls, in order, when it is fed this exchange
  bead.json    the bead as bd shows it: what the engine builds the brief and the prompt from
  plan.json    writer and reviewer cases: the plan the run goes by (a planner case's plan is its answer)
  answer.json  the answer the lane returned, as delegate's worker-run output carries it (`data`)
  input.txt    the prompt the engine sent for that call, the worktree as <WT>; UPDATE_GOLDEN=1 rewrites it (so does dev/record_exchange.py
               --prompt, which keeps the text a real run sent)

`replay` runs the engine with the fake route (support/fake_route.Script) answering the recorded role's call with answer.json, then checks
that the parser takes the answer, the engine called the roles meta.json lists, the call's input is input.txt, and its size is under
the role's cap (domain/lanes/caps). A prompt, schema or parser change that breaks a recorded exchange fails here."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.contracts import answers
from taskloop.domain.lanes import caps
from taskloop.domain.lanes.roles import ROLES

ROOT = Path(__file__).resolve().parents[2]
EXCHANGES = ROOT / "tests" / "fixtures" / "exchanges"
WT = "<WT>"


class Halt(BaseException):
    """Ends a planner replay after the plan: what comes next runs the plan's own checks, which a test cannot."""


def halter(seen: list[Any]) -> Any:
    """A scripted answer that ends the run and keeps the route script (the call record) in `seen`: run_engine returns nothing on a raise."""
    def halt(script: Any, *_: Any) -> dict[str, Any]:
        seen.append(script)
        raise Halt()
    return halt


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Exchange:
    role: str
    case: str
    dir: Path
    meta: dict[str, Any]
    bead: dict[str, Any]
    answer: dict[str, Any]
    plan: dict[str, Any]

    @property
    def node(self) -> str:
        return str(self.meta["node"])

    @property
    def name(self) -> str:
        return f"{self.role}/{self.case}"

    @property
    def input_file(self) -> Path:
        return self.dir / "input.txt"

    def answers(self, seen: list[Any]) -> dict[str, list[Any]]:
        """What the fake route answers per node: this exchange's answer for its node, the plain clean answers for the rest."""
        from support import engine_case as te  # noqa: PLC0415  (the engine tests' fixtures: loaded only by a test)
        out: dict[str, list[Any]] = {"plan": [self.plan], "write": [te.WRITE], "review": [te.CLEAN]}
        out[self.node] = [self.answer]
        if self.role == "planner":
            out["write"] = [halter(seen)]
        return out


def load(role: str, case: str) -> Exchange:
    d = EXCHANGES / role / case
    meta, answer = read(d / "meta.json"), read(d / "answer.json")
    plan = answer if role == "planner" else read(d / "plan.json")
    return Exchange(role, case, d, meta, read(d / "bead.json"), answer, plan)


def cases() -> list[Exchange]:
    return [load(r.name, c.name) for r in sorted(EXCHANGES.iterdir()) if r.is_dir() for c in sorted(r.iterdir()) if c.is_dir()]


def replay(test: Any, ex: Exchange) -> None:
    """Run the engine on the exchange's bead with its answer in place, and check the golden. `test` is a te.EngineTest."""
    test.assertEqual(answers.check(ex.node, False, ex.answer), [], f"{ex.name}: the parser rejects the recorded answer")
    test.store.put(ex.bead)
    seen: list[Any] = []
    try:
        rc, script = test.run_engine(ex.answers(seen), bead=ex.bead["id"])
    except Halt:
        script, rc = seen[0], 0
    calls = [role for role, _, _ in script.calls]
    test.assertEqual(calls, ex.meta["calls"], f"{ex.name}: the engine made other calls than recorded (rc {rc})")
    sent = script.prompts[script.nodes.index(ex.node)].replace(str(test.wt), WT)
    role = ROLES[ex.node]
    test.assertIsNone(caps.check(role, sent), f"{ex.name}: the recorded input is over the {role} cap")
    if os.environ.get("UPDATE_GOLDEN"):
        ex.input_file.write_text(sent, encoding="utf-8")
    test.assertEqual(ex.input_file.read_text(encoding="utf-8"), sent, f"{ex.name}: input.txt differs (UPDATE_GOLDEN=1 rewrites it)")
    if ex.role != "planner":
        test.assertEqual(rc, 0, f"{ex.name}: the engine did not accept the run")
