import asyncio
import csv
import io
import os
import random
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from collector.app import create_app
from collector.config import Settings
from collector.protocol import EVENT_TYPES, decode
from collector.receiver import Receiver, Runtime
from collector.store import Store, timestamp, utc_now


class ProtocolTests(unittest.TestCase):
    def test_protocol_matches_firmware_decoder(self):
        compiler = shutil.which("c++") or shutil.which("g++")
        self.assertIsNotNone(compiler, "A C++ compiler is required for firmware protocol parity")
        root = Path(__file__).resolve().parents[2]
        packets = []
        for source in ("prop-controller-1", "prop-controller-2", "prop-controller-3", "-", "a" * 63):
            for event in EVENT_TYPES:
                reasons = ("cooldown_finished", "stopped") if event == "sequence.ready" else ("",)
                for item in range(1, 5):
                    for reason in reasons:
                        packets.append(f"HC1|{source}|{event}|{item}|{reason}".encode())
        invalid = [
            b"", b"HC1", b"HC2|node|sensor.triggered|1|", b"HC1||sensor.triggered|1|",
            b"HC1|bad source|sensor.triggered|1|", b"HC1|node|relay.on|1|",
            b"HC1|node|sensor.triggered|0|", b"HC1|node|sensor.triggered|5|",
            b"HC1|node|sensor.triggered|12|", b"HC1|node|sensor.triggered|-1|",
            b"HC1|node|sensor.triggered|1|stopped", b"HC1|node|sensor.triggered|1||",
            b"HC1|node|sequence.ready|1|", b"HC1|node|sequence.ready|1|other",
            b"HC1|node\0name|sensor.triggered|1|", b"HC1|NODE|sensor.triggered|1|",
            b"HC1|node|sequence.ready|1|stopped\n", b"HC1|" + b"a" * 64 + b"|sensor.triggered|1|",
            b"x" * 129, b"\xff",
        ]
        rng = random.Random(18512)
        packets += invalid + [rng.randbytes(rng.randrange(151)) for _ in range(500)]
        expected = []
        for packet in packets:
            try:
                decode(packet)
                expected.append("1")
            except ValueError:
                expected.append("0")
        for packet in invalid:
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                decode(packet)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "parity.cpp"
            binary = Path(folder) / "parity"
            source.write_text('''#include "packages/controller-events.h"
#include <iostream>
#include <string>
int main() {
  std::string hex;
  while (std::getline(std::cin, hex)) {
    std::string packet;
    for (size_t i = 0; i < hex.size(); i += 2)
      packet.push_back(static_cast<char>(std::stoul(hex.substr(i, 2), nullptr, 16)));
    controller_events::Event event;
    std::cout << controller_events::decode(packet, event) << '\\n';
  }
}
''')
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(root), str(source), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], input="\n".join(p.hex() for p in packets) + "\n", text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), expected)

    def test_no_insecure_token_default(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Settings.from_env()


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(32)
        self.settings = Settings(api_token=self.token, database=Path(self.temp.name) / "events.sqlite3",
                                 udp_host="127.0.0.1", udp_port=0, retention_days=0)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()
        self.headers = {"Authorization": "Bearer " + self.token}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def get(self, path, **kwargs):
        return self.client.get(path, headers=self.headers, **kwargs)

    def send(self, packets):
        port = self.app.state.runtime.transport.get_extra_info("sockname")[1]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for packet in packets:
                sender.sendto(packet, ("127.0.0.1", port))

    def wait_for(self, key, value):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.get("/api/v1/status").json()
            if status["counters"][key] == value:
                return status
            time.sleep(.01)
        self.fail(f"Timed out waiting for {key}={value}")

    def test_udp_all_controllers_invalid_and_duplicate_packets(self):
        packets = [f"HC1|prop-controller-{i}|sequence.started|{i}|".encode() for i in range(1, 4)]
        self.send(packets + [packets[0], b"invalid", b"x" * 2048])
        status = self.wait_for("packets_received", 6)
        status = self.wait_for("events_written", 4)
        self.assertEqual(status["counters"]["invalid_packets"], 2)
        self.assertEqual(status["counters"]["write_errors"], 0)
        self.assertEqual(status["stored_events"], 4)
        events = self.get("/api/v1/events?order=asc").json()["events"]
        self.assertEqual([e["source"] for e in events], ["prop-controller-1", "prop-controller-2", "prop-controller-3", "prop-controller-1"])
        self.assertEqual(events[0]["raw_packet"], packets[0].decode())
        self.assertEqual(events[0]["sender_ip"], "127.0.0.1")
        self.assertEqual(len(self.get("/api/v1/controllers").json()["controllers"]), 3)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def seed(self):
        self.app.state.runtime.store.insert(decode(b"HC1|prop-controller-1|sequence.started|1|"), "2026-10-31T18:00:00.000000Z", ("192.0.2.1", 18512))
        self.app.state.runtime.store.insert(decode(b"HC1|prop-controller-2|sensor.triggered|2|"), "2026-10-31T18:00:01.000000Z", ("192.0.2.2", 18512))
        self.app.state.runtime.store.insert(decode(b"HC1|prop-controller-1|sequence.ready|1|stopped"), "2026-10-31T18:00:02.000000Z", ("192.0.2.1", 18512))

    def test_authentication_and_read_only_api(self):
        for path in ("status", "controllers", "events", "summary", "events.csv"):
            self.assertEqual(self.client.get("/api/v1/" + path).status_code, 401)
            self.assertEqual(self.client.get("/api/v1/" + path, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/events", headers=self.headers, json={}).status_code, 405)
        self.assertEqual(self.client.delete("/api/v1/events", headers=self.headers).status_code, 405)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("script-src 'self'", self.client.get("/").headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/ui/app.js").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
        self.assertIn("security", schema["paths"]["/api/v1/events"]["get"])
        self.assertEqual(self.get("/api/v1/events").headers["Cache-Control"], "no-store")

    def test_unavailable_storage_has_degraded_health_and_no_path_leak(self):
        with patch.object(self.app.state.runtime.store, "status", side_effect=OSError("private database path")):
            self.assertEqual(self.client.get("/healthz").status_code, 503)
            response = self.get("/api/v1/status")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private database path", response.text)

    def test_filters_pagination_and_polling(self):
        self.seed()
        first = self.get("/api/v1/events?limit=2&order=asc").json()
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_after_id"], 2)
        self.assertIsNone(first["next_before_id"])
        self.assertEqual([e["id"] for e in self.get("/api/v1/events?after_id=2&order=asc").json()["events"]], [3])
        newest = self.get("/api/v1/events?limit=2").json()
        self.assertEqual(newest["next_before_id"], 2)
        self.assertEqual([e["id"] for e in self.get("/api/v1/events?before_id=2").json()["events"]], [1])
        selection = {"since": "2026-10-31T12:00:00-06:00", "until": "2026-10-31T18:00:02Z"}
        self.assertEqual(len(self.get("/api/v1/events", params=selection).json()["events"]), 2)
        result = self.get("/api/v1/events?source=prop-controller-1&event=sequence.ready&item=1&reason=stopped").json()
        self.assertEqual([e["id"] for e in result["events"]], [3])
        self.assertEqual(self.get("/api/v1/summary?source=prop-controller-1").json()["total"], 2)
        self.assertEqual(self.get("/api/v1/events?after_id=999").json()["events"], [])
        for query in ("limit=1001", "limit=0", "item=5", "event=other", "source=bad%20name", "order=other", "after_id=-1", "since=2026-10-31T18:00:00", "since=2026-11-01T00:00:00Z&until=2026-10-01T00:00:00Z", "after_id=3&before_id=2"):
            with self.subTest(query=query):
                self.assertEqual(self.get("/api/v1/events?" + query).status_code, 422)

    def test_csv_export_is_paginated_and_formula_safe(self):
        self.seed()
        self.app.state.runtime.store.insert(decode(b"HC1|-node|sensor.triggered|1|"), utc_now(), ("192.0.2.3", 18512))
        response = self.get("/api/v1/events.csv?limit=2")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source"], "'-node")
        self.assertEqual(response.headers["X-Has-More"], "true")
        self.assertEqual(response.headers["X-Next-Before-Id"], "3")

    def test_restart_preserves_records_and_ids(self):
        self.send([b"HC1|prop-controller-1|sensor.triggered|1|"])
        self.wait_for("events_written", 1)
        self.client.__exit__(None, None, None)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()
        self.assertEqual(self.get("/api/v1/status").json()["stored_events"], 1)
        self.send([b"HC1|prop-controller-2|sensor.triggered|1|"])
        self.wait_for("events_written", 1)
        self.assertEqual([e["id"] for e in self.get("/api/v1/events?order=asc").json()["events"]], [1, 2])


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_and_storage_failure_are_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(api_token=secrets.token_urlsafe(32), database=Path(folder) / "events.sqlite3", udp_host="127.0.0.1", udp_port=0, queue_size=1)
            runtime = Runtime(settings)
            receiver = Receiver(runtime)
            packet = b"HC1|prop-controller-1|sequence.started|1|"
            receiver.datagram_received(packet, ("192.0.2.1", 18512))
            receiver.datagram_received(packet, ("192.0.2.1", 18512))
            self.assertEqual(runtime.counters.queue_overflows, 1)
            with patch.object(runtime.store, "insert", side_effect=OSError("test storage failure")):
                writer = asyncio.create_task(runtime.write_loop())
                await asyncio.wait_for(runtime.queue.join(), 3)
                self.assertEqual(runtime.counters.write_errors, 1)
                self.assertEqual(runtime.storage_error, "OSError")
                self.assertFalse(runtime.healthy())
            receiver.datagram_received(packet, ("192.0.2.1", 18512))
            await asyncio.wait_for(runtime.queue.join(), 3)
            self.assertIsNone(runtime.storage_error)
            self.assertEqual(runtime.counters.events_written, 1)
            writer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await writer
            runtime.store.close()

    async def test_shutdown_drains_queue_and_port_conflict_fails_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(api_token=secrets.token_urlsafe(32), database=Path(folder) / "events.sqlite3", udp_host="127.0.0.1", udp_port=0)
            runtime = Runtime(settings)
            await runtime.start()
            port = runtime.transport.get_extra_info("sockname")[1]
            conflicting = Runtime(Settings(api_token=settings.api_token, database=Path(folder) / "other.sqlite3", udp_host="127.0.0.1", udp_port=port))
            with self.assertRaises(OSError):
                await conflicting.start()
            Receiver(runtime).datagram_received(b"HC1|prop-controller-1|sequence.started|1|", ("192.0.2.1", 18512))
            await runtime.stop()
            store = Store(settings.database)
            self.assertEqual(store.status()["stored_events"], 1)
            store.close()


class RetentionTests(unittest.TestCase):
    def test_retention_preserves_monotonic_ids_and_disabled_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "events.sqlite3")
            event = decode(b"HC1|prop-controller-1|sequence.started|1|")
            store.insert(event, timestamp(datetime.now(timezone.utc) - timedelta(days=100)), ("192.0.2.1", 1))
            self.assertEqual(store.purge(0), 0)
            self.assertEqual(store.purge(90), 1)
            store.insert(event, utc_now(), ("192.0.2.1", 1))
            self.assertEqual(store.events({}, 1, "asc")["events"][0]["id"], 2)
            store.close()


if __name__ == "__main__":
    unittest.main()
