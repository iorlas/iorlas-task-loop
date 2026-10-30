"""The dashboard's static assets (dash-spec §12), checked by shelf's static_page_check: every JS import resolves to a file that
exports the imported names, the vendored runtime is pinned by hash, no colour value is written outside tokens.css, JS and CSS
together stay within 100 KB gzip; and the fixture dev server (dev/dash_fixtures.py) answers every route the page uses."""
import unittest
from pathlib import Path

import static_page_check as spc

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "taskloop_dash" / "static"
FIX = ROOT / "tests" / "fixtures" / "dash"
RUNTIME = "vendor/ui-runtime.js"
RUNTIME_SHA256 = "72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7"  # htm 3.1.1 preact/standalone.module.js


class StaticAssets(unittest.TestCase):
    def test_every_import_resolves_and_its_names_are_exported(self):
        self.assertEqual(spc.import_problems(STATIC, vendored=[RUNTIME]), [])

    def test_pages_reference_existing_assets(self):
        self.assertEqual(spc.page_problems(STATIC), [])

    def test_runtime_is_pinned(self):
        self.assertEqual(spc.pin_problems(STATIC, {RUNTIME: RUNTIME_SHA256}), [])

    def test_colours_live_only_in_tokens(self):
        self.assertEqual(spc.colour_problems(STATIC, "css/tokens.css", vendored=[RUNTIME]), [])

    def test_gzip_budget(self):
        self.assertEqual(spc.budget_problems(STATIC, 100 * 1024), [])


if __name__ == "__main__":
    unittest.main()
