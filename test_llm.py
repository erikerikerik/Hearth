import unittest
from app.llm import assert_loopback


class LoopbackGuardTests(unittest.TestCase):
    def test_loopback_is_accepted(self):
        for url in ("http://127.0.0.1:8081/v1", "http://localhost:8081/v1/", "http://[::1]:8081/v1"):
            self.assertTrue(assert_loopback(url))

    def test_anything_else_is_refused(self):
        for url in ("https://api.example.com/v1", "http://192.168.1.20:8081/v1", "http://0.0.0.0:8081/v1",
                    "http://localhost.evil.test/v1", "http://10.0.0.5/v1"):
            with self.assertRaises(ValueError):
                assert_loopback(url)


class StreamParsingTests(unittest.TestCase):
    def test_reasoning_is_separated_from_spoken_content(self):
        import json, threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from app.llm import stream_chat, stream_events

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200); self.end_headers()
                for delta in ({"reasoning": "hmm "}, {"reasoning_content": "ok "}, {"content": "Hello."}):
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            def log_message(self, *a): pass
        server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = "http://127.0.0.1:%d/v1" % server.server_port
            kinds = [k for k, _ in stream_events(base, "m", [{"role": "user", "content": "x"}])]
            self.assertEqual(kinds, ["reasoning", "reasoning", "content"])
            self.assertEqual("".join(stream_chat(base, "m", [{"role": "user", "content": "x"}])), "Hello.")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
