"""Owner writes are gated before body reads or dispatch; HTTP runs over in-memory streams."""

import io
import json
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tlkernel.dash import WRITES

from tldash.http import make_handler

HOST = "127.0.0.1:7878"
HEADERS = {"Host": HOST, "Origin": f"http://{HOST}", "X-Taskloop-Dash": "1", "Content-Type": "application/json"}


class WritePolicy(Case):
    def request(self, headers, verb="answer", extra=(), port=7878):
        dash = mock.Mock()
        dash.writes.post.return_value = (200, {"ok": True})
        body = b'{"text":"go"}'
        fields = [*headers.items(), *extra, ("Content-Length", str(len(body)))]
        head = (f"POST /api/{verb} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields) + "\r\n").encode()
        reader, writer = io.BytesIO(head + body), io.BytesIO()
        sock = mock.Mock()
        sock.makefile.side_effect = [mock.Mock(wraps=stream, close=mock.Mock()) for stream in (reader, writer)]
        handler = make_handler(dash, port, ["127.0.0.1", "100.101.102.103"], Path("."), "test")
        # StreamRequestHandler uses a socket writer unless wbufsize is nonzero.
        with mock.patch.object(handler, "wbufsize", -1):
            handler(sock, ("127.0.0.1", 12345), mock.Mock())
        return writer.getvalue(), dash.writes.post, reader.tell() - len(head)

    def assert_rejected(self, headers, code=403, extra=()):
        for verb in WRITES:
            with self.subTest(verb=verb, headers=headers, extra=extra):
                response, post, consumed = self.request(headers, verb, extra)
                assert f" {code} ".encode() in response.split(b"\r\n", 1)[0]
                post.assert_not_called()
                assert consumed == 0

    def test_host_must_be_known_and_use_the_bound_port(self):
        for host in (None, "evil.example:7878", "127.0.0.1:9999", "100.101.102.104:7878", "localhost",
                     "user@127.0.0.1:7878", "127.0.0.1:7878/path", "127.0.0.1:bad", "[::1", "127.0.0.1:7878#x",
                     "[::1]evil:7878", "127.0.0.1:7878, evil.example"):
            headers = {**HEADERS, "Host": host} if host is not None else {k: v for k, v in HEADERS.items() if k != "Host"}
            if host is not None:
                headers["Origin"] = f"http://{host}"
            self.assert_rejected(headers)
            self.assert_rejected({k: v for k, v in headers.items() if k != "Origin"})

    def test_origin_must_match_host_scheme_and_port(self):
        for origin in ("null", "", "http://evil.example:7878", "http://localhost:7878", "https://127.0.0.1:7878",
                       "http://127.0.0.1:9999", "http://127.0.0.1:7878/path", "http://user@127.0.0.1:7878",
                       "http://127.0.0.1:7878?x", "http://[::1", "http://127.0.0.1:7878 http://evil.example"):
            self.assert_rejected({**HEADERS, "Origin": origin})

    def test_custom_header_is_required_even_with_same_origin(self):
        for value in (None, "0", "", "1, 1"):
            headers = {k: v for k, v in HEADERS.items() if k != "X-Taskloop-Dash"}
            if value is not None:
                headers["X-Taskloop-Dash"] = value
            self.assert_rejected(headers)
            self.assert_rejected({k: v for k, v in headers.items() if k != "Origin"})

    def test_only_json_media_type_is_accepted(self):
        for value in (None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "application/jsonp"):
            headers = {k: v for k, v in HEADERS.items() if k != "Content-Type"}
            if value is not None:
                headers["Content-Type"] = value
            self.assert_rejected(headers, 415)

    def test_duplicate_security_headers_are_refused(self):
        for name, value in HEADERS.items():
            self.assert_rejected(HEADERS, 415 if name == "Content-Type" else 403, [(name, value)])

    def test_every_write_accepts_same_origin_or_header_only_clients(self):
        for host in (HOST, "localhost:7878", "[::1]:7878", "100.101.102.103:7878"):
            for origin in (f"http://{host}", None):
                headers = {**HEADERS, "Host": host, "Content-Type": "Application/JSON; charset=utf-8"}
                if origin is None:
                    del headers["Origin"]
                else:
                    headers["Origin"] = origin
                for verb in WRITES:
                    with self.subTest(host=host, origin=origin, verb=verb):
                        response, post, consumed = self.request(headers, verb)
                        assert b" 200 " in response.split(b"\r\n", 1)[0]
                        assert json.loads(response.split(b"\r\n\r\n", 1)[1]) == {"ok": True}
                        post.assert_called_once_with(verb, {"text": "go"})
                        assert consumed > 0

    def test_default_http_port_and_host_case_are_normalized(self):
        response, post, _ = self.request({**HEADERS, "Host": "LOCALHOST", "Origin": "http://localhost:80"}, port=80)
        assert b" 200 " in response.split(b"\r\n", 1)[0]
        post.assert_called_once()

    def test_browser_write_helper_sends_the_required_header(self):
        api = Path(__file__).resolve().parents[3] / "packages/dash/src/tldash/static/js/api.js"
        write = api.read_text(encoding="utf-8").split("export async function write(", 1)[1].split("const LIVE_WAIT_S", 1)[0]
        assert "'X-Taskloop-Dash': '1'" in write
        assert "'Content-Type': 'application/json'" in write
