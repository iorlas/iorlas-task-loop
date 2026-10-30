"""A red check the writer could not reproduce (a Unity analyzer build its sandbox cannot run) reaches it in the next round as the
check's own diagnostics: file:line, rule, message (domain/checks/diagnostics.py), not a trimmed log (tl-9un.13)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.engine_case import CLEAN, PLAN, WRITE
from support.engine_case import EngineTest as Base

N = 30
FRAMEWORKS = ("netstandard2.1", "net8.0", "net9.0")  # MSBuild says each diagnostic once per target framework, the suffix differs


def roslyn(n: int) -> list[str]:
    return [f"/work/client/Assets/Scripts/Unit{n:02}.cs({n + 3},{n % 9 + 1}): warning CA18{n:02}: Member 'M{n}' is unused "
            f"[/work/client/Game.csproj::TargetFramework={fw}]" for fw in FRAMEWORKS]


def analyzer_log(open_ones: list[int]) -> str:
    noise = [f"  Determining projects to restore... step {i}" for i in range(80)]
    body = [ln for n in open_ones for ln in roslyn(n)]
    return "\n".join([*noise[:40], *body, *noise[40:], "Build FAILED.", f"    {len(body)} Warning(s)", "Time Elapsed 00:01:12"])


class DiagnosticsTest(Base):
    def writer_prompts(self, s):
        return [p for p, c in zip(s.prompts, s.calls, strict=False) if c[0] == "worker"]

    def fixes(self) -> set[int]:
        f = Path(self.tmp.name) / "fixes.txt"  # outside the worktree: the code the writer "fixed", which the check reads
        return {int(x) for x in f.read_text().split()} if f.exists() else set()

    def analyzers(self):
        """The check: red with a log of the diagnostics still open, green when every one is fixed."""
        def run(cwd, env):
            open_ones = [n for n in range(N) if n not in self.fixes()]
            return (1, analyzer_log(open_ones)) if open_ones else (0, "")
        return procsim.fake("dotnet-analyzers", run)

    def writer(self):
        """A writer that cannot build: it fixes the diagnostics its prompt lists, and nothing else."""
        def write(script, node, cwd, resume):
            seen = {int(m) for m in re.findall(r"Unit(\d\d)\.cs:", script.prompts[-1])}
            (Path(self.tmp.name) / "fixes.txt").write_text(" ".join(str(n) for n in sorted(self.fixes() | seen)))
            return WRITE
        return write

    def run_engine_with_writer(self):
        write = self.writer()
        return self.run_engine({"plan": [PLAN], "write": [write] * 4, "review": [CLEAN]}, max_check_tries=4,
                               checks=[{"id": "unity-analyzers", "cmd": self.analyzers(), "group": "static"}])

    def test_the_next_brief_lists_each_diagnostic_once_with_file_line_rule_and_message(self):
        _rc, s = self.run_engine_with_writer()
        brief = self.writer_prompts(s)[1]
        self.assertIn("/work/client/Assets/Scripts/Unit07.cs:10:8: warning CA1807: Member 'M7' is unused", brief)
        self.assertEqual(brief.count("Unit07.cs"), 1)  # once, not once per target framework
        self.assertNotIn("[/work/client/Game.csproj", brief)

    def test_two_failing_rounds_become_one_fix_round_when_the_writer_gets_the_diagnostics(self):
        rc, s = self.run_engine_with_writer()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.writer_prompts(s)), 2)  # the write, then one fix round that the green check ends

    def test_a_container_check_is_not_one_the_writer_is_told_to_run(self):
        eng = self.checks_engine(checks=[{"id": "lint", "cmd": "true", "group": "static", "in": "container", "writer": True}],
                                 container={"image": "x"})
        self.assertTrue(eng.checker.split().engine_only("true"))
