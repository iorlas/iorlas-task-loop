"""domain/checks/diagnostics.py: the diagnostics of the formats our registered checks print, and the trimmed words for any other."""
import unittest

from taskloop.domain.checks import diagnostics as dg
from taskloop.domain.checks.diagnostics import Diagnostic


def only(text):
    (d,) = dg.parse(text)
    return d


class Formats(unittest.TestCase):
    def test_roslyn_with_its_project_suffix_cut(self):
        d = only("A/B.cs(42,13): warning CA1822: Member 'J' can be static [/w/G.csproj::TargetFramework=net8.0]")
        self.assertEqual(d, Diagnostic("A/B.cs", 42, 13, "warning", "CA1822", "Member 'J' can be static"))

    def test_msbuild_error_without_a_column(self):
        d = only("/w/X.cs(7): error CS0103: The name 'y' does not exist")
        self.assertEqual((d.path, d.line, d.col, d.severity, d.rule), ("/w/X.cs", 7, 0, "error", "CS0103"))

    def test_ruff_full_format_message_then_arrow(self):
        d = only("F401 [*] `os` imported but unused\n --> src/a.py:1:8\n  |\n1 | import os\n  |        ^^")
        self.assertEqual(d, Diagnostic("src/a.py", 1, 8, "", "F401", "`os` imported but unused"))

    def test_ruff_concise_format(self):
        d = only("src/a.py:1:8: F401 [*] `os` imported but unused")
        self.assertEqual((d.path, d.line, d.col, d.rule, d.message), ("src/a.py", 1, 8, "F401", "`os` imported but unused"))

    def test_pyrefly_message_then_arrow(self):
        d = only("ERROR `int` is not assignable to `str` [bad-assignment]\n --> a/b.py:3:10")
        self.assertEqual(d, Diagnostic("a/b.py", 3, 10, "error", "bad-assignment", "`int` is not assignable to `str`"))

    def test_generic_path_line_col_message_with_ansi_colour(self):
        d = only("\x1b[1mweb/app.ts:10:5: error: Cannot find name 'x'\x1b[0m")
        self.assertEqual((d.path, d.line, d.col, d.severity, d.message), ("web/app.ts", 10, 5, "error", "Cannot find name 'x'"))

    def test_a_clock_line_is_no_diagnostic(self):
        self.assertEqual(dg.parse("Time Elapsed 00:01:12\nBuild FAILED.\n12:30:45: started"), [])

    def test_a_repeat_is_said_once_in_the_order_of_the_log(self):
        log = "b.cs(2,1): warning A1: m [p.csproj::TargetFramework=x]\na.cs(1,1): warning A2: n [p.csproj::TargetFramework=x]\n" \
              "b.cs(2,1): warning A1: m [p.csproj::TargetFramework=y]"
        self.assertEqual([d.path for d in dg.parse(log)], ["b.cs", "a.cs"])


class Render(unittest.TestCase):
    def test_output_with_no_diagnostic_is_the_trimmed_log(self):
        text = "\n".join(f"line {i}" for i in range(500)) + "\nboom"
        out = dg.render(dg.of_check("make", 2, text, "/l.log"), 1000)
        self.assertLess(len(out.encode()), 1000)
        self.assertIn("boom", out)
        self.assertNotIn("diagnostic", out)

    def test_the_list_is_capped_and_says_how_many_it_left_out(self):
        text = "\n".join(f"f{i}.cs({i},1): warning CA{i:04}: message number {i}" for i in range(200))
        out = dg.render(dg.of_check("analyze", 1, text, "/l.log"), 2000)
        self.assertLess(len(out.encode()), 2000)
        self.assertIn("200 diagnostics", out)
        self.assertRegex(out, r"\.\.\. \d+ more not shown")
        self.assertIn("f0.cs:0:1: warning CA0000: message number 0", out)

    def test_a_long_message_is_cut(self):
        out = dg.render(dg.of_check("c", 1, "a.py:1:1: E1 " + "x" * 1000, ""), 4000)
        self.assertLess(len(out), 600)
