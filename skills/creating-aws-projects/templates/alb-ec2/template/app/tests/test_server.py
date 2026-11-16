import json
import os
import sys
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server  # noqa: E402


class RouteTest(unittest.TestCase):
    def test_health_is_ok(self):
        self.assertEqual((200, {"status": "ok"}), server.route("GET", "/health", "c-1"))

    def test_hello_returns_the_correlation_id_and_source_hash(self):
        status, body = server.route("GET", "/hello", "c-1")

        self.assertEqual(200, status)
        self.assertEqual("c-1", body["correlation_id"])
        self.assertIn("source_sha256", body)

    def test_unknown_path_is_not_found(self):
        self.assertEqual(404, server.route("GET", "/nope", "c-1")[0])

    def test_post_is_not_allowed(self):
        self.assertEqual(405, server.route("POST", "/hello", "c-1")[0])

    def test_source_hash_ignores_tests(self):
        app = os.path.join(os.path.dirname(__file__), "..")

        self.assertEqual(64, len(server.SOURCE_SHA256))
        self.assertEqual(server.source_hash(server.Path(app).resolve()), server.SOURCE_SHA256)

    def test_unsafe_correlation_id_is_replaced(self):
        self.assertNotEqual("a b\nforged", server.correlation_id_from({"x-correlation-id": "a b\nforged"}))


class InstanceIdTest(unittest.TestCase):
    def test_instance_id_comes_from_imdsv2_with_a_token(self):
        calls = []

        def fetch(method, url, headers):
            calls.append((method, url, headers))
            return "token-1" if method == "PUT" else "i-0123456789abcdef0\n"

        self.assertEqual("i-0123456789abcdef0", server.instance_id(fetch))
        self.assertEqual(("PUT", "http://169.254.169.254/latest/api/token"), calls[0][:2])
        self.assertIn("X-aws-ec2-metadata-token-ttl-seconds", calls[0][2])
        self.assertEqual(("GET", "http://169.254.169.254/latest/meta-data/instance-id",
                          {"X-aws-ec2-metadata-token": "token-1"}), calls[1])

    def test_unreachable_metadata_service_falls_back_to_the_hostname(self):
        def fetch(method, url, headers):
            raise OSError("timed out")

        self.assertEqual(server.socket.gethostname(), server.instance_id(fetch))

    def test_unexpected_answer_falls_back_to_the_hostname(self):
        self.assertEqual(server.socket.gethostname(), server.instance_id(lambda m, u, h: "<html>proxy</html>"))

    def test_no_hostname_is_still_an_answer(self):
        def fetch(method, url, headers):
            raise OSError("timed out")

        with unittest.mock.patch.object(server.socket, "gethostname", side_effect=OSError("no name")):
            self.assertEqual("unknown", server.instance_id(fetch))

    def test_hello_names_the_instance_that_answered(self):
        self.assertEqual(server.instance(), server.route("GET", "/hello", "c-1")[1]["instance"])


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def test_hello_echoes_the_correlation_id(self):
        request = urllib.request.Request(self.base + "/hello", headers={"x-correlation-id": "abc-123"})
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())

            self.assertEqual("abc-123", response.headers["x-correlation-id"])
        self.assertEqual("hello", body["message"])

    def test_unknown_path_returns_json_404(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.base + "/nope", timeout=5)

        self.assertEqual(404, raised.exception.code)
        self.assertEqual({"message": "not found"}, json.loads(raised.exception.read()))


if __name__ == "__main__":
    unittest.main()
