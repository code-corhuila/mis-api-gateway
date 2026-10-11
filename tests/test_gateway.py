from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import subprocess
import time
import unittest
import urllib.error
import urllib.request
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "mis-gateway-check-" + str(os.getpid())
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "deploy/compose.test.yml")]


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            subprocess.run(COMPOSE + ["up", "-d", "--build", "--wait", "--wait-timeout", "90"], check=True)
            port = subprocess.check_output(COMPOSE + ["port", "gateway", "8080"], text=True).strip().rsplit(":", 1)[1]
            cls.base = "http://127.0.0.1:" + port
        except Exception:
            subprocess.run(COMPOSE + ["logs", "--tail", "30", "gateway"])
            subprocess.run(COMPOSE + ["down", "-v"])
            raise

    @classmethod
    def tearDownClass(cls):
        subprocess.run(COMPOSE + ["down", "-v"], check=True)

    def setUp(self):
        time.sleep(0.15)

    def request(self, path, method="GET", headers=None, body=None):
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as failure:
            response = failure
        with response:
            data = response.read()
            return response.status, response.headers, json.loads(data) if data else None

    def assert_error(self, response, status, code):
        actual, headers, body = response
        self.assertEqual(status, actual)
        self.assertEqual(code, body["error"])
        self.assertEqual(headers["X-Correlation-Id"], body["traceId"])

    def test_health_and_missing_bearer(self):
        status, headers, body = self.request("/health")
        self.assertEqual((status, body), (200, {"status": "UP"}))
        self.assertEqual(str(UUID(headers["X-Correlation-Id"])), headers["X-Correlation-Id"])
        self.assert_error(self.request("/api/v1/medications"), 401, "UNAUTHORIZED")

    def test_public_routes_and_protected_forwarding(self):
        self.assertEqual(200, self.request("/api/v1/auth/jwks")[0])
        result = self.request("/api/v1/suppliers?page=2", headers={"Authorization": "Bearer stub-token",
            "X-Correlation-Id": "trace-001", "X-User-Role": "ADMIN"})
        self.assertEqual(200, result[0])
        self.assertEqual("trace-001", result[2]["correlation"])
        self.assertEqual("page=2", result[2]["query"])
        self.assertIsNone(result[2]["roleHeader"])
        self.assertTrue(result[2]["authorizationPresent"])

    def test_cors(self):
        headers = {"Origin": "http://localhost:4200", "Access-Control-Request-Method": "POST"}
        status, response, _ = self.request("/api/v1/medications", method="OPTIONS", headers=headers)
        self.assertEqual(204, status)
        self.assertEqual(headers["Origin"], response["Access-Control-Allow-Origin"])
        self.assertIn("Idempotency-Key", response["Access-Control-Allow-Headers"])
        self.assertIsNone(response.get("Access-Control-Allow-Credentials"))
        self.assert_error(self.request("/health", headers={"Origin": "http://untrusted.example"}), 403, "FORBIDDEN")
        self.assert_error(self.request("/health", method="OPTIONS"), 400, "VALIDATION_ERROR")

    def test_inventory_routes(self):
        self.assert_error(self.request("/api/v1/entries", method="POST", body=b"{}"), 401, "UNAUTHORIZED")
        for path in ("/api/v1/entries", "/api/v1/entries/entry-id", "/api/v1/entries/entry-id/activate", "/api/v1/entries/entry-id/cancel"):
            time.sleep(0.15)
            result = self.request(path, method="POST", body=b"{}", headers={"Authorization": "Bearer stub-token", "Idempotency-Key": "inventory-001"})
            self.assertEqual(200, result[0])
        self.assert_error(self.request("/api/v1/entries/id/delete", headers={"Authorization": "Bearer stub-token"}), 404, "NOT_FOUND")

    def test_invalid_correlation_body_and_path(self):
        self.assert_error(self.request("/health", headers={"X-Correlation-Id": "bad/value"}), 400, "VALIDATION_ERROR")
        self.assert_error(self.request("/api/v1/auth/login", method="POST", body=b"x" * 65537), 413, "PAYLOAD_TOO_LARGE")
        self.assert_error(self.request("/not-a-route"), 404, "NOT_FOUND")

    def test_inventory_query_routes(self):
        for path in ("/api/v1/stock", "/api/v1/movements"):
            time.sleep(0.15)
            self.assert_error(self.request(path), 401, "UNAUTHORIZED")
            time.sleep(0.15)
            result = self.request(path + "?page=2&limit=1", headers={"Authorization": "Bearer stub-token"})
            self.assertEqual(200, result[0])
            self.assertEqual("page=2&limit=1", result[2]["query"])
        self.assert_error(self.request("/api/v1/stock/id", headers={"Authorization": "Bearer stub-token"}), 404, "NOT_FOUND")

    def test_exit_routes(self):
        self.assert_error(self.request("/api/v1/exits", method="POST", body=b"{}"), 401, "UNAUTHORIZED")
        for path in ("/api/v1/exits", "/api/v1/exits/exit-id"):
            time.sleep(0.15)
            self.assertEqual(200, self.request(path, headers={"Authorization": "Bearer stub-token"})[0])
        self.assert_error(self.request("/api/v1/exits/id/cancel", headers={"Authorization": "Bearer stub-token"}), 404, "NOT_FOUND")

    def test_rejects_invalid_configuration(self):
        for origin in ("", "http://localhost:4200;injected"):
            result = subprocess.run(["docker", "run", "--rm", "--read-only", "--tmpfs",
                "/tmp:uid=101,gid=101,mode=0700", "-e", "GATEWAY_ALLOWED_ORIGINS=" + origin,
                PROJECT + "-gateway"], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)

    def test_upstream_failure_does_not_disable_other_routes(self):
        subprocess.run(COMPOSE + ["stop", "catalog"], check=True)
        try:
            self.assert_error(self.request("/api/v1/medications", headers={"Authorization": "Bearer stub-token"}), 503, "SERVICE_UNAVAILABLE")
            self.assertEqual(200, self.request("/api/v1/suppliers", headers={"Authorization": "Bearer stub-token"})[0])
            self.assertEqual(200, self.request("/health")[0])
        finally:
            subprocess.run(COMPOSE + ["start", "catalog"], check=True)
            time.sleep(1)

    def test_upstream_timeout(self):
        self.assert_error(self.request("/api/v1/medications?delay=12", headers={"Authorization": "Bearer stub-token"}), 503, "SERVICE_UNAVAILABLE")

    def test_z_rate_limit(self):
        time.sleep(3)
        with ThreadPoolExecutor(max_workers=30) as executor:
            responses = list(executor.map(lambda _: self.request("/api/v1/suppliers",
                headers={"Authorization": "Bearer stub-token"}), range(70)))
        limited = [response for response in responses if response[0] == 429]
        self.assertTrue(limited)
        for response in limited:
            self.assert_error(response, 429, "TOO_MANY_REQUESTS")
            self.assertEqual("1", response[1]["Retry-After"])


if __name__ == "__main__":
    unittest.main()
