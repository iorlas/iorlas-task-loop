"""The page and its modules served read-only from the static dir (assets.py via http.route)."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import support.paths  # noqa: E402, F401

from taskloop_dash.http import route  # noqa: E402


class Static(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.out = base / "outside.js"
        self.out.write_text("secret")
        self.s = base / "static"
        for name, text in {
            "index.html": "<page>", "css/kit.css": "a{}", "js/app.js": "export{}",
            "js/components.js": "dev", "components.html": "dev", ".hidden.js": "x", "js/x.py": "py", "js/.env.js": "x",
        }.items():
            (self.s / name).parent.mkdir(parents=True, exist_ok=True)
            (self.s / name).write_text(text)
        (self.s / "link.js").symlink_to(self.out)

    def get(self, path):
        got = route(None, self.s, path, {})  # type: ignore[arg-type]
        return got[:3] if got else None

    def test_serves_types(self):
        self.assertEqual(self.get("/js/app.js"), (200, b"export{}", "text/javascript; charset=utf-8"))
        self.assertEqual(self.get("/css/kit.css"), (200, b"a{}", "text/css; charset=utf-8"))

    def test_the_root_is_the_page(self):
        for p in ("/", "/index.html"):
            self.assertEqual(self.get(p), (200, b"<page>", "text/html; charset=utf-8"))

    def test_rejected_is_404(self):
        bad = ["/../outside.js", "/js/../../outside.js", "/%2e%2e/outside.js", "/js/%2e%2e/%2e%2e/outside.js", "/js%2f..%2f..%2foutside.js",
               "/js%2fapp.js/..", "//etc/passwd", "/js\\app.js", "/js/app.js%00.py", "/link.js", "/js/x.py", "/.hidden.js", "/js/.env.js",
               "/components.html", "/js/components.js", "/js", "/js/", "/css", "/nope.js", "/index.html/x", "/v2", "/live.html"]
        for p in bad:
            with self.subTest(p=p):
                self.assertIsNone(self.get(p))

    def test_size_cap(self):
        (self.s / "js/big.js").write_bytes(b"x" * 2_000_001)
        self.assertIsNone(self.get("/js/big.js"))

    def test_a_missing_page_is_no_route(self):
        (self.s / "index.html").unlink()
        self.assertIsNone(self.get("/"))


if __name__ == "__main__":
    unittest.main()
