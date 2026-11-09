import json
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import handler  # noqa: E402

CONTEXT = SimpleNamespace(aws_request_id="req-123")


class HandlerTest(unittest.TestCase):
    def test_echoes_correlation_id_from_header(self):
        response = handler({"headers": {"x-correlation-id": "corr-1"}, "routeKey": "GET /hello"}, CONTEXT)

        self.assertEqual(200, response["statusCode"])
        self.assertEqual("corr-1", response["headers"]["x-correlation-id"])
        self.assertEqual("req-123", json.loads(response["body"])["requestId"])

    def test_falls_back_to_request_id_without_header(self):
        response = handler({}, CONTEXT)

        self.assertEqual("req-123", response["headers"]["x-correlation-id"])

    def test_logs_correlation_id(self):
        with self.assertLogs(level="INFO") as logs:
            handler({"headers": {"x-correlation-id": "corr-2"}}, CONTEXT)

        self.assertEqual("corr-2", logs.records[0].correlation_id)


if __name__ == "__main__":
    unittest.main()
