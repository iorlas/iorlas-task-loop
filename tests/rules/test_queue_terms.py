"""The merge queue says "gates in flight" (docs/glossary.md; design section 6). The retired words `window` and `lookahead` must not name that
concept in the queue modules: not as an identifier, an argument, an attribute, nor as a string that is a config key, an event or a metric
name. (An account's usage window is the delegate's own word and lives outside these modules.)"""
import ast
import re
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"
QUEUE_GLOBS = ("domain/land/queue*.py", "app/land/queue*.py", "app/land/in_flight*.py", "contracts/queue*.py")
RETIRED = re.compile(r"window|lookahead", re.IGNORECASE)
NAME_LIKE = re.compile(r"[\w.\-]+")  # a config key, event or metric name; prose (docstrings, messages) has spaces


def names_in(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for n in ast.walk(tree):
        match n:
            case ast.Name(id=name) | ast.Attribute(attr=name) | ast.FunctionDef(name=name) | ast.ClassDef(name=name) | ast.arg(arg=name):
                found.append(name)
            case ast.keyword(arg=str() as name) | ast.alias(name=name):
                found.append(name)
            case ast.Constant(value=str() as text) if NAME_LIKE.fullmatch(text):
                found.append(text)
    return found


def queue_files() -> list[Path]:
    return sorted({f for g in QUEUE_GLOBS for f in SRC.glob(g)})


def offenders(path: Path) -> list[str]:
    return sorted({n for n in names_in(ast.parse(path.read_text(encoding="utf-8"))) if RETIRED.search(n)})


class QueueTerms(Case):
    def test_the_queue_modules_exist_to_be_checked(self):
        assert any(f.name.startswith("queue") for f in queue_files())

    def test_no_queue_module_names_gates_in_flight_with_a_retired_word(self):
        bad = {str(f.relative_to(SRC)): o for f in queue_files() if (o := offenders(f))}
        assert bad == {}, "say in_flight, in_flight_floor, max_in_flight, queue_depth (docs/glossary.md), not window or lookahead"

    def test_the_check_sees_every_kind_of_name(self):
        code = ("WASTE_WINDOW = 1\nclass LookaheadQueue:\n    def window_size(self, lookahead): return self.window\n"
                "f(window=1)\nKEY = 'land.queue.window'\nfrom x import window as w\n'a window of time'\n")
        assert set(offenders_of(code)) == {"WASTE_WINDOW", "LookaheadQueue", "window_size", "lookahead", "window", "land.queue.window"}


def offenders_of(code: str) -> list[str]:
    return [n for n in names_in(ast.parse(code)) if RETIRED.search(n)]
