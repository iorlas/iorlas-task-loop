"""The v2 page and its modules served read-only from the static dir (assets.py via http.plain_route)."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import support.paths  # noqa: E402, F401

from taskloop_dash.http import plain_route  # noqa: E402


class Static(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.out = base / "outside.js"
        self.out.write_text("secret")
        self.s = base / "static"
        for name, text in {
            "index.html": "old", "live.html": "live", "v2.html": "<v2>", "css/kit.css": "a{}", "js/app.js": "export{}",
            "js/components.js": "dev", "components.html": "dev", ".hidden.js": "x", "js/x.py": "py", "js/.env.js": "x",
        }.items():
            (self.s / name).parent.mkdir(parents=True, exist_ok=True)
            (self.s / name).write_text(text)
        (self.s / "link.js").symlink_to(self.out)
        self.page = self.s / "index.html"

    def get(self, path):
        return plain_route(None, self.page, self.s / "live.html", path, {})  # type: ignore[arg-type]

    def test_serves_types(self):
        self.assertEqual(self.get("/js/app.js"), (200, b"export{}", "text/javascript; charset=utf-8"))
        self.assertEqual(self.get("/css/kit.css"), (200, b"a{}", "text/css; charset=utf-8"))
        self.assertEqual(self.get("/live.html"), (200, b"live", "text/html; charset=utf-8"))

    def test_v2_aliases(self):
        for p in ("/v2", "/v2.html"):
            self.assertEqual(self.get(p), (200, b"<v2>", "text/html; charset=utf-8"))
        self.assertEqual(self.get("/"), (200, b"old", "text/html; charset=utf-8"))

    def test_rejected_is_404(self):
        bad = ["/../outside.js", "/js/../../outside.js", "/%2e%2e/outside.js", "/js/%2e%2e/%2e%2e/outside.js", "/js%2f..%2f..%2foutside.js",
               "/js%2fapp.js/..", "//etc/passwd", "/js\\app.js", "/js/app.js%00.py", "/link.js", "/js/x.py", "/.hidden.js", "/js/.env.js",
               "/components.html", "/js/components.js", "/js", "/js/", "/css", "/nope.js", "/v2.html/x"]
        for p in bad:
            with self.subTest(p=p):
                self.assertIsNone(self.get(p))

    def test_size_cap(self):
        (self.s / "js/big.js").write_bytes(b"x" * 2_000_001)
        self.assertIsNone(self.get("/js/big.js"))

    def test_missing_v2_is_404(self):
        (self.s / "v2.html").unlink()
        self.assertEqual(self.get("/v2"), (404, b"not found", "text/plain"))


if __name__ == "__main__":
    unittest.main()
