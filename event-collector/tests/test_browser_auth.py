import secrets
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from collector.app import create_app
from collector.browser_auth import COOKIE_NAME, SESSION_SECONDS
from collector.config import Settings


class BrowserSessionTests(unittest.TestCase):
    origin = "https://collector.example:8089"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(32)
        self.settings = Settings(api_token=self.token, database=Path(self.temp.name) / "events.sqlite3",
                                 udp_host="127.0.0.1", udp_port=0)
        self.client = TestClient(create_app(self.settings), base_url=self.origin)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, remember=True, **kwargs):
        return self.client.post("/api/v1/session", json={"remember": remember},
                                headers={"Authorization": "Bearer " + self.token, "Origin": self.origin}, **kwargs)

    def test_remembered_session_authenticates_queries_and_survives_restart(self):
        response = self.login()
        self.assertEqual(response.status_code, 204)
        cookie = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1", "Max-Age=604800"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotIn(self.token, cookie)
        value = self.client.cookies.get(COOKIE_NAME)
        for path in ("session", "status", "controllers", "events", "summary", "events.csv"):
            self.assertEqual(self.client.get("/api/v1/" + path).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/events", headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.client.__exit__(None, None, None)
        self.client = TestClient(create_app(self.settings), base_url=self.origin)
        self.client.__enter__()
        self.client.cookies.set(COOKIE_NAME, value, domain="collector.example", path="/api/v1")
        self.assertEqual(self.client.get("/api/v1/events").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/events").headers["Cache-Control"], "no-store")

    def test_cookie_without_remember_and_signout(self):
        response = self.login(remember=False)
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("Max-Age", response.headers["set-cookie"])
        self.assertNotIn("expires=", response.headers["set-cookie"].lower())
        response = self.client.delete("/api/v1/session", headers={"Origin": self.origin})
        self.assertEqual(response.status_code, 204)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertIn("Path=/api/v1", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/v1/events").status_code, 401)
        self.assertEqual(self.client.delete("/api/v1/session", headers={"Origin": self.origin}).status_code, 204)
        self.assertEqual(self.client.get("/api/v1/events", headers={"Authorization": "Bearer " + self.token}).status_code, 200)

    def test_expiry_tampering_and_token_rotation_reject_cookie(self):
        now = 1_800_000_000
        with patch("collector.browser_auth.time.time", return_value=now):
            self.login()
            value = self.client.cookies.get(COOKIE_NAME)
        with patch("collector.browser_auth.time.time", return_value=now + SESSION_SECONDS - 1):
            self.assertEqual(self.client.get("/api/v1/events", headers={"Cookie": f"{COOKIE_NAME}={value}"}).status_code, 200)
        with patch("collector.browser_auth.time.time", return_value=now + SESSION_SECONDS):
            self.assertEqual(self.client.get("/api/v1/events", headers={"Cookie": f"{COOKIE_NAME}={value}"}).status_code, 401)
        parts = value.split(".")
        parts[1] = str(int(parts[1]) + 1)
        with patch("collector.browser_auth.time.time", return_value=now):
            for invalid in ("", "broken", "x" * 2000, ".".join(parts), value[:-1] + ("0" if value[-1] != "0" else "1")):
                with self.subTest(value=invalid):
                    self.assertEqual(self.client.get("/api/v1/events", headers={"Cookie": f"{COOKIE_NAME}={invalid}"}).status_code, 401)
            rotated = replace(self.settings, api_token=secrets.token_urlsafe(32))
            with TestClient(create_app(rotated), base_url=self.origin) as other:
                self.assertEqual(other.get("/api/v1/events", headers={"Cookie": f"{COOKIE_NAME}={value}"}).status_code, 401)

    def test_session_creation_requires_token_and_same_origin(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = self.client.post("/api/v1/session", json={"remember": True}, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("set-cookie", response.headers)
        self.login()
        self.assertEqual(self.client.post("/api/v1/session", json={"remember": True}).status_code, 401)
        for origin in ("https://other.example", "https://collector.example:9090", "null"):
            with self.subTest(origin=origin):
                headers = {"Origin": origin, "Authorization": "Bearer " + self.token}
                self.assertEqual(self.client.post("/api/v1/session", json={"remember": True}, headers=headers).status_code, 403)
                self.assertEqual(self.client.delete("/api/v1/session", headers={"Origin": origin}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/events").status_code, 200)

        headers = {"Sec-Fetch-Site": "cross-site", "Authorization": "Bearer " + self.token}
        self.assertEqual(self.client.post("/api/v1/session", json={"remember": True}, headers=headers).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)

    def test_https_proxy_origin_sets_secure_cookie_without_trusting_forwarded_proto(self):
        # SWAG preserves Host but Uvicorn intentionally ignores proxy headers.
        response = self.client.post("http://collector.example:8089/api/v1/session", json={"remember": True},
                                    headers={"Origin": self.origin, "Authorization": "Bearer " + self.token})
        self.assertEqual(response.status_code, 204)
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/v1/events").status_code, 200)
        self.assertEqual(self.client.get("http://collector.example:8089/api/v1/events").status_code, 401)

    def test_plain_http_still_supports_browser_and_bearer_auth(self):
        with TestClient(create_app(self.settings), base_url="http://collector.example:8080") as client:
            response = client.post("/api/v1/session", json={"remember": True}, headers={
                "Origin": "http://collector.example:8080", "Authorization": "Bearer " + self.token,
                "X-Forwarded-Proto": "https"})
            self.assertEqual(response.status_code, 204)
            self.assertNotIn("Secure", response.headers["set-cookie"])
            self.assertEqual(client.get("/api/v1/events").status_code, 200)


if __name__ == "__main__":
    unittest.main()
