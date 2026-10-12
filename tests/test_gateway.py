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

    def test_workflow_routes(self):
        self.assert_error(self.request("/api/v1/sagas/receive-supplies", method="POST", body=b"{}"), 401, "UNAUTHORIZED")
        for path, method, key in (("/api/v1/sagas/receive-supplies", "POST", "workflow-start-001"),
                                  ("/api/v1/sagas/saga-id", "GET", None),
                                  ("/api/v1/sagas/saga-id/resume", "POST", None)):
            time.sleep(0.15)
            headers = {"Authorization": "Bearer stub-token", "X-Correlation-Id": "workflow-trace"}
            if key is not None:
                headers["Idempotency-Key"] = key
            result = self.request(path, method=method, body=b"{}" if method == "POST" else None, headers=headers)
            self.assertEqual(200, result[0])
            self.assertEqual("workflow-trace", result[2]["correlation"])
            self.assertEqual(path, result[2]["path"])
            self.assertEqual(method, result[2]["method"])
            self.assertEqual(key, result[2]["idempotencyKey"])
        self.assert_error(self.request("/api/v1/sagas/id/delete", headers={"Authorization": "Bearer stub-token"}), 404, "NOT_FOUND")

    def test_catalog_maintenance_and_conditional_cors(self):
        headers = {"Authorization": "Bearer stub-token", "If-Match": '"2"'}
        for path, method in (("/api/v1/medications/id", "PUT"), ("/api/v1/medications/id/deactivate", "POST")):
            time.sleep(0.15)
            response = self.request(path, method=method, body=b"{}", headers=headers)
            self.assertEqual(200, response[0])
            self.assertEqual((path, method, '"2"'), (response[2]["path"], response[2]["method"], response[2]["ifMatch"]))
            self.assertEqual('"3"', response[1]["ETag"])
        preflight = self.request("/api/v1/medications/id", method="OPTIONS",
            headers={"Origin": "http://localhost:4200", "Access-Control-Request-Method": "PUT"})
        self.assertEqual(204, preflight[0])
        self.assertIn("If-Match", preflight[1]["Access-Control-Allow-Headers"])
        self.assertIn("ETag", preflight[1]["Access-Control-Expose-Headers"])
        self.assert_error(self.request("/api/v1/medications/id/deactivate", method="POST", body=b"{}"), 401, "UNAUTHORIZED")

    def test_workflow_compensation_route(self):
        self.assert_error(self.request("/api/v1/sagas/id/compensate", method="POST", body=b"{}"), 401, "UNAUTHORIZED")
        result = self.request("/api/v1/sagas/id/compensate", method="POST", body=b"{}", headers={"Authorization": "Bearer stub-token"})
        self.assertEqual(200, result[0])
        self.assertEqual("/api/v1/sagas/id/compensate", result[2]["path"])
        self.assertEqual("POST", result[2]["method"])
        self.assertIsNone(result[2]["idempotencyKey"])

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

    def test_expiry_alert_route_preserves_query_bearer_trace_and_cors(self):
        self.assert_error(self.request("/api/v1/alerts/expiry"), 401, "UNAUTHORIZED")
        query = "page=2&limit=20&state=OPEN&severity=EXPIRED&lotId=11111111-1111-4111-8111-111111111111"
        response = self.request("/api/v1/alerts/expiry?"+query, headers={"Authorization": "Bearer stub-token",
            "X-Correlation-Id": "expiry-route", "X-User-Role": "ADMIN", "Origin": "http://localhost:4200"})
        self.assertEqual(200, response[0])
        self.assertEqual(("GET","/api/v1/alerts/expiry",query), (response[2]["method"],response[2]["path"],response[2]["query"]))
        self.assertTrue(response[2]["authorizationPresent"]); self.assertIsNone(response[2]["roleHeader"])
        self.assertEqual("expiry-route",response[2]["correlation"])
        self.assertEqual(["expiry-route"],response[1].get_all("X-Correlation-Id"))
        self.assertEqual("http://localhost:4200",response[1]["Access-Control-Allow-Origin"])
        preflight = self.request("/api/v1/alerts/expiry",method="OPTIONS",headers={"Origin":"http://localhost:4200","Access-Control-Request-Method":"GET"})
        self.assertEqual(204,preflight[0])

    def test_expiry_internal_and_unpublished_subroutes_remain_private(self):
        for path in ("/api/v1/internal/alerts/expiry/evaluate", "/api/v1/internal/events/stock-changed",
                     "/api/v1/alerts/expiry/evaluate", "/api/v1/alerts/expiry/id", "/api/v1/alerts/expiry/"):
            time.sleep(.15)
            self.assert_error(self.request(path,headers={"Authorization":"Bearer stub-token"}),404,"NOT_FOUND")

    def test_expiry_owner_permissions_and_method_errors_are_not_replaced(self):
        response = self.request("/api/v1/alerts/expiry",headers={"Authorization":"Bearer stub-forbidden","X-Correlation-Id":"expiry-denied"})
        self.assert_error(response,403,"FORBIDDEN")
        self.assertEqual("Owner rejected request.",response[2]["message"])
        response = self.request("/api/v1/alerts/expiry",method="POST",body=b"{}",headers={"Authorization":"Bearer stub-token"})
        self.assert_error(response,405,"METHOD_NOT_ALLOWED")
        self.assertEqual("GET, HEAD",response[1]["Allow"])

    def test_expiry_inventory_failure_is_isolated(self):
        subprocess.run(COMPOSE+["stop","inventory"],check=True)
        try:
            self.assert_error(self.request("/api/v1/alerts/expiry",headers={"Authorization":"Bearer stub-token"}),503,"SERVICE_UNAVAILABLE")
            self.assertEqual(200,self.request("/health")[0])
            self.assertEqual(200,self.request("/api/v1/suppliers",headers={"Authorization":"Bearer stub-token"})[0])
        finally:
            subprocess.run(COMPOSE+["start","inventory"],check=True); time.sleep(1)

    def test_receipt_routes(self):
        self.assert_error(self.request("/api/v1/receipts", method="POST", body=b"{}"), 401, "UNAUTHORIZED")
        for path in ("/api/v1/receipts", "/api/v1/receipts/id", "/api/v1/receipts/id/confirm", "/api/v1/receipts/id/void"):
            time.sleep(0.15)
            self.assertEqual(200, self.request(path, headers={"Authorization": "Bearer stub-token"})[0])
        self.assert_error(self.request("/api/v1/receipts/id/delete", headers={"Authorization": "Bearer stub-token"}), 404, "NOT_FOUND")

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
