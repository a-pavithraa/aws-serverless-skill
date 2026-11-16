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

    def test_hello_names_the_secrets_it_received_without_their_values(self):
        env = {"SECRET_NAMES": "DB_PASSWORD,API_TOKEN", "DB_PASSWORD": "s3cr3t-value", "API_TOKEN": ""}

        body = server.route("GET", "/hello", "c-1", env)[1]

        self.assertEqual(["DB_PASSWORD"], body["secrets_loaded"])
        self.assertNotIn("s3cr3t-value", json.dumps(body))

    def test_hello_without_secrets_lists_none(self):
        self.assertEqual([], server.route("GET", "/hello", "c-1", {})[1]["secrets_loaded"])

    def test_hello_names_the_instance_that_answered(self):
        self.assertEqual(server.instance(), server.route("GET", "/hello", "c-1")[1]["instance"])
        self.assertTrue(server.instance())

    def test_unknown_path_is_not_found(self):
        self.assertEqual(404, server.route("GET", "/nope", "c-1")[0])

    def test_post_is_not_allowed(self):
        self.assertEqual(405, server.route("POST", "/hello", "c-1")[0])

    def test_unsafe_correlation_id_is_replaced(self):
        self.assertNotEqual("a b\nforged", server.correlation_id_from({"x-correlation-id": "a b\nforged"}))


class TaskIdTest(unittest.TestCase):
    ENV = {"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc"}

    def test_task_id_is_the_last_part_of_the_task_arn(self):
        urls = []

        def fetch(url):
            urls.append(url)
            return json.dumps({"TaskARN": "arn:aws:ecs:us-east-1:123456789012:task/web/0123456789abcdef"}).encode()

        self.assertEqual("0123456789abcdef", server.task_id(self.ENV, fetch))
        self.assertEqual(["http://169.254.170.2/v4/abc/task"], urls)

    def test_unreachable_metadata_endpoint_falls_back_to_the_hostname(self):
        def fetch(url):
            raise OSError("connection refused")

        self.assertEqual(server.socket.gethostname(), server.task_id(self.ENV, fetch))

    def test_unexpected_metadata_falls_back_to_the_hostname(self):
        self.assertEqual(server.socket.gethostname(), server.task_id(self.ENV, lambda url: b"not json"))

    def test_outside_ecs_the_hostname_is_used(self):
        self.assertEqual(server.socket.gethostname(), server.task_id({}, lambda url: self.fail("no endpoint to call")))

    def test_no_hostname_is_still_an_answer(self):
        with unittest.mock.patch.object(server.socket, "gethostname", side_effect=OSError("no name")):
            self.assertEqual("unknown", server.task_id({}))


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
