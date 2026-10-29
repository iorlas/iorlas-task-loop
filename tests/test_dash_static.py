"""Dashboard v2 static assets (dash-spec §12): every JS import resolves to a file that exports the imported names, the vendored
runtime is pinned by hash, no colour value is written outside tokens.css, JS and CSS together stay within 100 KB gzip, and the
fixture dev server (dev/dash_fixtures.py) answers every route the page uses."""
import gzip
import hashlib
import importlib.util
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "taskloop_dash" / "static"
FIX = ROOT / "tests" / "fixtures" / "dash_v2"
VENDOR = STATIC / "vendor" / "ui-runtime.js"
VENDOR_SHA256 = "72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7"  # htm 3.1.1 preact/standalone.module.js
BUDGET_GZIP = 100 * 1024
# the v1 page, retired when v2 reaches the slice 4 gate (dash-spec §12)
LEGACY = {"index.html", "live.html"}

IMPORT = re.compile(r"""^\s*import\s+(?:(\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+)?['"]([^'"]+)['"]""", re.M)
EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", re.M)
EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}", re.M)
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b(?![-\w])|\brgba?\(|\bhsla?\(")


def page_files() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*") if p.is_file() and p.suffix in (".js", ".css", ".html")
                  and p != VENDOR and p.name not in LEGACY)


def exports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = set(EXPORT.findall(text))
    for group in EXPORT_LIST.findall(text):
        names |= {n.split(" as ")[-1].strip() for n in group.split(",") if n.strip()}
    return names


def strip_css_selectors(text: str) -> str:
    """CSS with comments dropped; an id selector (#ph) is not a colour."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


class StaticAssets(unittest.TestCase):
    def test_every_import_resolves_and_its_names_are_exported(self):
        js = sorted(p for p in STATIC.rglob("*.js") if p != VENDOR)
        self.assertTrue(js)
        vendor = VENDOR.read_text(encoding="utf-8")
        for path in js:
            for names, spec in IMPORT.findall(path.read_text(encoding="utf-8")):
                with self.subTest(file=path.relative_to(STATIC).as_posix(), spec=spec):
                    self.assertTrue(spec.startswith("."), "imports are relative, no CDN")
                    target = (path.parent / spec).resolve()
                    self.assertTrue(target.is_file(), f"{spec} does not exist")
                    if not names.startswith("{"):
                        continue
                    wanted = {n.split(" as ")[0].strip() for n in names.strip("{}").split(",") if n.strip()}
                    missing = ({n for n in wanted if not re.search(rf"\b{n}\b", vendor)} if target == VENDOR
                               else wanted - exports(target))
                    self.assertFalse(missing, f"{spec} does not export {sorted(missing)}")

    def test_pages_reference_existing_assets(self):
        for page in ("v2.html", "components.html"):
            text = (STATIC / page).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'(?:href|src)="/', f"{page}: assets by relative url, so the page works wherever it is served")
            for ref in re.findall(r'(?:href|src)="(?!https?:)([^"]+)"', text):
                with self.subTest(page=page, ref=ref):
                    self.assertTrue((STATIC / ref).is_file())

    def test_runtime_is_pinned(self):
        self.assertEqual(hashlib.sha256(VENDOR.read_bytes()).hexdigest(), VENDOR_SHA256,
                         "vendor/ui-runtime.js changed: it is never edited, only replaced with a new pin")

    def test_colours_live_only_in_tokens(self):
        for path in page_files():
            if path.name == "tokens.css":
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".css":
                text = strip_css_selectors(text)
            for n, line in enumerate(text.splitlines(), 1):
                # a CSS id selector or an html id is not a colour: only values after ":" or in style/JS strings count
                hits = [m.group(0) for m in COLOUR.finditer(line) if not re.match(r"#[a-zA-Z][\w-]*\s*[{,.:\s>]", line[m.start():])]
                with self.subTest(file=path.relative_to(STATIC).as_posix(), line=n):
                    self.assertFalse(hits, f"colour outside tokens.css: {hits} in {line.strip()[:120]}")

    def test_gzip_budget(self):
        shipped = [p for p in STATIC.rglob("*") if p.suffix in (".js", ".css") and p.name not in LEGACY]
        total = sum(len(gzip.compress(p.read_bytes(), 9)) for p in shipped)
        self.assertLessEqual(total, BUDGET_GZIP, f"JS+CSS is {total / 1024:.1f} KB gzip, budget 100 KB")


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
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
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
        code, body = self.get("/api/v2/snapshot")
        self.assertEqual(code, 200)
        version = json.loads(body)["version"]
        self.assertEqual(self.get(f"/api/v2/snapshot?since={version}")[0], 304)

    def test_every_bead_and_live_fixture(self):
        snap = json.loads((FIX / "snapshot.json").read_text(encoding="utf-8"))
        project = {b["id"]: b["project"] for b in snap["beads"]}
        for kind in ("bead", "live"):
            for f in sorted((FIX / kind).glob("*.json")):
                with self.subTest(kind=kind, id=f.stem):
                    code, body = self.get(f"/api/v2/{kind}?project={project[f.stem]}&id={f.stem}")
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body), json.loads(f.read_text(encoding="utf-8")))
        self.assertEqual(self.get("/api/v2/bead?project=x&id=nope")[0], 404)

    def test_every_write_and_a_bad_body(self):
        for verb, body in json.loads((FIX / "writes.json").read_text(encoding="utf-8")).items():
            with self.subTest(verb=verb):
                self.assertEqual(self.post(f"/api/v2/{verb}", json.dumps(body).encode()), 200)
        self.assertEqual(self.post("/api/v2/answer", b'{"project": "x", "unknown": 1}'), 400)
        self.assertEqual(self.post("/api/v2/nope", b"{}"), 404)


if __name__ == "__main__":
    unittest.main()
