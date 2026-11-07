"""The engine and the skill name no consumer repo: what a repo needs is in its .task-loop.json. A name here would make the next
reader think the engine serves one project (tl-w7lt.32)."""
import re
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("src/taskloop", "skills/task-loop")
SKIP = ("_vendor",)
SUFFIXES = {".py", ".md", ".json"}
CONSUMERS = re.compile(r"lifesim", re.I)


def offenders() -> list[str]:
    found = []
    for top in ROOTS:
        for path in sorted((ROOT / top).rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES or any(part in SKIP for part in path.parts):
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if CONSUMERS.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    return found


class NoConsumerNames(Case):
    def test_no_file_of_the_engine_or_the_skill_names_a_consumer_repo(self):
        assert offenders() == []
