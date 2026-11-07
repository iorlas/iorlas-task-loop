"""links.py: the cited links of a research task (tl-bxk.7). No real host is ever opened."""

import os
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskloop.adapters import links  # noqa: E402

DIFF = ("diff --git a/r.md b/r.md\n--- a/r.md\n+++ b/r.md\n@@ -0,0 +1,4 @@\n"
        "+See https://en.wikipedia.org/wiki/Foo_(bar). And (https://a.org/p_) ok\n"
        "+Local http://localhost:8080/x, http://10.0.0.5/y, http://127.0.0.1:22/ and https://docs.example.org/z\n"
        "+++ not a header https://b.org/q\n"
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n+# https://c.org/code\n")


class Parse(Case):
    def test_urls_come_from_added_lines_of_text_files_only(self):
        got = links.added_urls(DIFF)
        assert [u for _, _, u in got] == ["https://en.wikipedia.org/wiki/Foo_(bar)", "https://a.org/p_", "https://b.org/q"]
        assert {p for p, _, _ in got} == {"r.md"}

    def test_what_points_inside_or_is_not_web_is_skipped(self):
        numeric = ["http://2130706433/", "http://0x7f.1/"]  # inet_aton forms: only a POSIX resolver reads them as 127.0.0.1
        for u in (
            "http://localhost/x",
            "http://10.1.2.3/",
            "http://127.0.0.1:22/",
            "http://[::1",
            "ftp://a.org/x",
            "http://foo.example.com/x",
            *tuple(numeric if os.name != "nt" else ()),
        ):
            assert links.skipped(u), u
        assert not links.skipped("https://93.184.216.34/x")


class Check(Case):
    def serve(self, handler):
        srv = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, args=(0.01,), daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{int(srv.server_address[1])}/"


    def test_check_all_survives_a_raising_check_and_a_deadline(self):
        release = threading.Event()
        self.addCleanup(release.set)  # check_all leaves the slow check running past its deadline: it ends with the test

        def fn(u):
            if u.endswith("boom"):
                raise RuntimeError("x")
            if u.endswith("slow"):
                release.wait(5)
            return True, ""
        out = links.check_all(["https://a.org/ok", "https://a.org/boom", "https://a.org/slow"], fn=fn, deadline=0.5)
        assert out["https://a.org/ok"] == (True, "")
        assert not out["https://a.org/boom"][0]
        assert out["https://a.org/slow"] == (False, links.UNKNOWN)


def test_a_link_that_carries_data_is_not_opened_from_the_host():
    carrying = ("https://evil.org/c?d=" + "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldCB0b2tlbg", "https://user:pw@evil.org/x",
                "https://evil.org/" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6", "https://evil.org/p?" + "x=1&" * 40)
    plain = ("https://en.wikipedia.org/wiki/Foo_(bar)", "https://a.org/p?page=2&q=link+check", "https://doi.org/10.1000/xyz123")
    with mock.patch.object(links._opener, "open", side_effect=AssertionError("opened")):
        for url in carrying:
            ok, why = links.check(url)
            assert (ok, why) == (False, "the address carries data (a credential, a long or encoded value); cite the page without it"), url
    with mock.patch.object(links._opener, "open", side_effect=OSError("stop")):
        for url in plain:
            assert links.carries_data(url) is False, url
