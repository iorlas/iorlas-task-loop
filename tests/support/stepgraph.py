"""The run's step graph as the code writes it: which steps each step can hand on to, read off the source of `Standalone.start_step`,
`Standalone.finish_step` and `stage_rounds.run_round_step` / `round_step` (their `step is Step.X` branches and the `Step.Y` they assign or
return in each), so a test never types the edges by hand. A step that ends the run hands on to nothing (None)."""
import ast
import inspect
import textwrap
from collections.abc import Callable

from taskloop.app.pipeline.standalone import Standalone
from taskloop.app.write import rounds as stage_rounds
from tlkernel.enums import Step

Graph = dict[Step, set[Step | None]]


def _steps(node: ast.AST) -> set[Step | None]:
    """The Step members (and None returns) a branch body assigns to `following` or returns."""
    out: set[Step | None] = set()
    for n in ast.walk(node):
        follows = isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "following" for t in n.targets)
        if (follows or isinstance(n, ast.Return)) and n.value is not None:
            for v in ast.walk(n.value):
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "Step":
                    out.add(Step[v.attr])
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value is None:
                out.add(None)
    return out


def _chain(fn: Callable[..., object], rest: set[Step]) -> Graph:
    """The `if step is Step.X: ... elif ... else:` chain of `fn`: each named branch's successors; the else branch's go to every step
    in `rest`. A Step name inside a body counts only when assigned or returned, never when compared."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    found: Graph = {}
    node: ast.If | None = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and "step is Step." in ast.unparse(n.test))
    named: set[Step] = set()
    while node is not None:
        name = Step[ast.unparse(node.test).rsplit("Step.", 1)[1].split()[0].rstrip(":)")]
        named.add(name)
        found[name] = _steps(ast.Module(body=node.body, type_ignores=[]))
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            continue
        for other in rest - named:
            found[other] = _steps(ast.Module(body=node.orelse, type_ignores=[]))
        node = None
    return found


def graph() -> Graph:
    out: Graph = {}
    out.update(_chain(Standalone.start_step, {Step.PLAN, Step.REPLAN}))
    out[Step.RESET] = {Step.PLAN}
    out.update(_chain(Standalone.finish_step, {Step.VERIFY}))
    rounds = _chain(stage_rounds.run_round_step, {Step.REVIEW})
    accepted = _steps(ast.parse(textwrap.dedent(inspect.getsource(stage_rounds.round_step))))  # an accepted stage: verify or the next one
    for step, nxt in rounds.items():
        out[step] = nxt | (accepted if step is Step.REVIEW else set())
    return out
