"""links.py: the cited links of a research task (tl-bxk.7). No real host is ever opened."""

import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

from taskloop.adapters import links  # noqa: E402


class Check(unittest.TestCase):
    def serve(self, handler):
        srv = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, args=(0.01,), daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{int(srv.server_address[1])}/"

    def test_check_gives_a_verdict_for_every_kind_of_failure_and_never_raises(self):
        class H(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(200 if self.path == "/ok" else 404)
                self.end_headers()
            do_GET = do_HEAD

            @override
            def log_message(self, format, *a):
                pass
        base = self.serve(H)
        self.assertEqual(links.check(base + "ok"), (True, ""))
        self.assertEqual(links.check(base + "gone"), (False, "HTTP 404"))
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        def greet():
            c = s.accept()
            c[0].sendall(b"SSH-2.0-OpenSSH\r\n")
            c[0].close()

        threading.Thread(target=greet, daemon=True).start()
        ok, why = links.check(f"http://127.0.0.1:{port}/", timeout=3)  # a non-HTTP server answers with garbage
        self.assertFalse(ok)
        self.assertTrue(why)
        s.close()


if __name__ == "__main__":
    unittest.main()
