"""The dashboard's static assets (dash-spec §12), checked by shelf's static_page_check: every JS import resolves to a file that
exports the imported names, the vendored runtime is pinned by hash, no colour value is written outside tokens.css, JS and CSS
together stay within 100 KB gzip; and the fixture dev server (dev/dash_fixtures.py) answers every route the page uses."""
import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
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


def load_dev_server():
    spec = importlib.util.spec_from_file_location("dash_fixtures_dev", ROOT / "dev" / "dash_fixtures.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DevServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mod = load_dev_server()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.make_handler("ok"))
        threading.Thread(target=cls.srv.serve_forever, args=(0.01,), daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def post(self, path: str, body: bytes) -> int:
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_pages_and_assets(self):
        for path in ("/", "/components.html", "/check.html"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 200)
        for p in STATIC.rglob("*"):
            if p.is_file() and p.suffix in (".js", ".css", ".html"):
                with self.subTest(asset=p.name):
                    self.assertEqual(self.get("/" + p.relative_to(STATIC).as_posix())[0], 200)
        self.assertEqual(self.get("/../dev/dash_fixtures.py")[0], 404)

    def test_snapshot_and_its_304(self):
        code, body = self.get("/api/snapshot")
        self.assertEqual(code, 200)
        version = json.loads(body)["version"]
        self.assertEqual(self.get(f"/api/snapshot?since={version}")[0], 304)

    def test_every_bead_and_live_fixture(self):
        snap = json.loads((FIX / "snapshot.json").read_text(encoding="utf-8"))
        project = {b["id"]: b["project"] for b in snap["beads"]}
        for kind in ("bead", "live"):
            for f in sorted((FIX / kind).glob("*.json")):
                with self.subTest(kind=kind, id=f.stem):
                    code, body = self.get(f"/api/{kind}?project={project[f.stem]}&id={f.stem}")
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body), json.loads(f.read_text(encoding="utf-8")))
        self.assertEqual(self.get("/api/bead?project=x&id=nope")[0], 404)

    def test_every_write_and_a_bad_body(self):
        for verb, body in json.loads((FIX / "writes.json").read_text(encoding="utf-8")).items():
            with self.subTest(verb=verb):
                self.assertEqual(self.post(f"/api/{verb}", json.dumps(body).encode()), 200)
        self.assertEqual(self.post("/api/answer", b'{"project": "x", "unknown": 1}'), 400)
        self.assertEqual(self.post("/api/nope", b"{}"), 404)


if __name__ == "__main__":
    unittest.main()
