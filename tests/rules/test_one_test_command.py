"""One way to run the tests: agents are told `just test` (the tests a change can break) and `pytest <file or dir>` for one slice, and
nothing that runs the whole suite. The agent-facing texts (AGENTS.md, CLAUDE.md, README.md, the skill, the engine's briefs)
must not name a whole-suite run: bare pytest, `pytest tests`, `-n auto`, the retired runners (suite.py, suite-docker.py),
`just test-fast`, `just test-all`, `just check-all`."""
import re
from pathlib import Path

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]
TEXTS = ("AGENTS.md", "CLAUDE.md", "README.md", "skills/task-loop/SKILL.md")
BRIEFS = ("packages/work/src/tlwork/prompts", "src/taskloop/app/*/prompts.py", "src/taskloop/app/write/review_prompt.py",
          "packages/work/src/tlwork/review/verify_prompt.py",
          "packages/pipeline/src/tlpipeline/reflect_prompt.py")
FORBIDDEN = re.compile(
    r"suite\.py|suite-docker|test-fast|test-all|check-all|-n auto"
    r"|\bpytest\s+-\S+"            # pytest with options and no path: the whole suite
    r"|\bpytest\s*(?:`|$)"         # bare pytest
    r"|\bpytest\s+tests(?:\s|`|$)",  # the whole tests folder
    re.M)


def agent_texts():
    yield from (ROOT / name for name in TEXTS)
    yield from sorted(p for pattern in BRIEFS for p in ROOT.glob(pattern if pattern.endswith(".py") else pattern + "/*.py"))


class OneTestCommand(Case):
    def test_no_agent_facing_text_names_a_whole_suite_run(self):
        found = []
        for path in agent_texts():
            for hit in FORBIDDEN.finditer(path.read_text(encoding="utf-8")):
                line = path.read_text(encoding="utf-8").count("\n", 0, hit.start()) + 1
                found.append(f"{path.relative_to(ROOT)}:{line}: {hit.group(0)!r}")
        assert found == [], "agents run `just test` (affected-only) or pytest on one file or folder, never the whole suite"

    def test_the_pattern_catches_what_it_is_for(self):
        for bad in ("uv run pytest", "uv run pytest -q", "pytest tests", "just test-fast", "dev/suite.py", "pytest -n auto"):
            with self.subTest(bad):
                assert FORBIDDEN.search(bad)
        for good in ("uv run pytest tests/land -q", "pytest tests/land/test_x.py::T::test", "pytest-xdist", "just test", "pytest classes"):
            with self.subTest(good):
                assert not FORBIDDEN.search(good)
