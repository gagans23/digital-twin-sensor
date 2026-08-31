import copy
import importlib.util
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import uuid
from argparse import Namespace
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from digital_twin_sensor import observability as obs
from digital_twin_sensor.cli import cmd_collect_once
from digital_twin_sensor.config import DEFAULT_CONFIG, write_config
from digital_twin_sensor.context_pack import build_context_pack
from digital_twin_sensor.opik_exporter import export_once
from digital_twin_sensor.resume import build_resume_view, resume_action
from digital_twin_sensor.store import EventStore


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "events.sqlite"

    def record(self):
        with obs.operation(self.db, "collection.sample") as root:
            with obs.operation(self.db, "collection.capture"):
                pass
            root.counts(stored=1, title="PRIVATE CANARY", events=True)

    def test_off_is_dependency_free_and_creates_no_log(self):
        self.record()
        self.assertFalse(obs.log_path(self.db).exists())
        self.assertEqual(obs.status(self.db)["mode"], "off")
        with patch("digital_twin_sensor.opik_exporter._sdk", side_effect=AssertionError("SDK imported")):
            self.assertEqual(export_once(self.db)["status"], "disabled")

    def test_schema_excludes_content_and_preserves_nesting(self):
        obs.configure(self.db, mode="local")
        self.record()
        trace = obs.status(self.db)["recent"][0]
        self.assertEqual(trace["counts"], {"stored": 1})
        self.assertEqual(trace["spans"][0]["parent_id"], trace["id"])
        self.assertNotIn("PRIVATE CANARY", json.dumps(trace))
        self.assertEqual(obs.log_path(self.db).stat().st_mode & 0o777, 0o600)

    def test_raw_exceptions_and_unknown_metadata_never_persist(self):
        obs.configure(self.db, mode="local")
        with self.assertRaisesRegex(ValueError, "SECRET_CANARY"):
            with obs.operation(self.db, "resume.action") as span:
                span.data["input"] = {"password": "SECRET_CANARY"}
                span.data["prompt"] = "SECRET_CANARY"
                raise ValueError("SECRET_CANARY card 4111111111111111")
        trace = obs.status(self.db)["recent"][0]
        self.assertEqual(trace["error"], "validation")
        self.assertNotIn("SECRET_CANARY", obs.log_path(self.db).read_bytes().decode(errors="ignore"))
        self.assertNotIn("4111111111111111", json.dumps(trace))

    def test_real_collection_and_resume_paths_are_instrumented(self):
        obs.configure(self.db, mode="local")
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.update(collection_paused=True, subject_id="SECRET_CANARY")
        config_path = Path(self.tmp.name) / "config.json"
        write_config(config, config_path)
        with redirect_stdout(io.StringIO()):
            cmd_collect_once(Namespace(db=self.db, config=config_path, dwell_seconds=15))
        build_resume_view(self.db, config)
        with self.assertRaises(ValueError):
            resume_action(self.db, config, {"action": "SECRET_CANARY"})
        build_context_pack([], config, db_path=self.db)
        recent = obs.status(self.db)["recent"]
        self.assertEqual({item["name"] for item in recent}, {"collection.sample", "resume.view", "resume.action", "context.pack"})
        self.assertEqual(next(item for item in recent if item["name"] == "collection.sample")["outcome"], "paused")
        self.assertNotIn("SECRET_CANARY", json.dumps(recent))

    def test_logging_failure_does_not_break_pipeline(self):
        obs.configure(self.db, mode="local")
        with patch.object(obs, "_save", side_effect=OSError("SECRET_CANARY")), self.assertLogs(obs.__name__) as logs:
            with patch.object(obs, "_last_warning", None):
                self.record()
        self.assertNotIn("SECRET_CANARY", str(logs.output))
        self.assertEqual(obs.status(self.db)["records"], 0)

    def test_lock_contention_does_not_stall_collection(self):
        obs.configure(self.db, mode="local")
        with obs.connect(self.db) as conn:
            conn.execute("BEGIN EXCLUSIVE")
            start = time.monotonic()
            self.record()
            self.assertLess(time.monotonic()-start, 0.25)

    def test_capture_is_bounded_and_retention_removes_pending(self):
        obs.configure(self.db, mode="opik", endpoint="http://127.0.0.1:5173/api")
        with patch.object(obs, "MAX_RECORDS", 3):
            for _ in range(6):
                self.record()
            self.assertEqual(obs.status(self.db)["records"], 3)
        with obs.connect(self.db) as conn:
            conn.execute("UPDATE records SET created=?", (time.time()-obs.RETENTION_SECONDS-1,))
            conn.commit()
        state = obs.status(self.db)
        self.assertEqual(state["records"], 0)
        self.assertEqual(state["exporter"]["dropped"], 6)

    def test_changing_consent_never_replays_a_backlog(self):
        obs.configure(self.db, mode="local")
        self.record()
        obs.configure(self.db, mode="opik", endpoint="http://localhost:5173/api")
        self.assertEqual(obs.status(self.db)["pending"], 0)
        self.record()
        self.assertEqual(obs.status(self.db)["pending"], 1)
        obs.configure(self.db, mode="off")
        obs.configure(self.db, mode="opik")
        self.assertEqual(obs.status(self.db)["pending"], 0)

    def test_reenable_and_purge_invalidate_inflight_local_traces(self):
        obs.configure(self.db, mode="local")
        with obs.operation(self.db, "resume.view"):
            obs.configure(self.db, mode="off")
            obs.configure(self.db, mode="local")
        self.assertEqual(obs.status(self.db)["records"], 0)
        with obs.operation(self.db, "resume.view"):
            obs.purge(self.db)
        self.assertEqual(obs.status(self.db)["records"], 0)

    def test_remote_requires_explicit_consent_and_safe_url(self):
        for endpoint in ("http://opik.example/api", "https://key:secret@opik.example/api", "https://opik.example/api?token=secret", "file:///tmp/opik", "https://opik.example/api#secret"):
            with self.assertRaises(ValueError):
                obs.configure(self.db, mode="opik", endpoint=endpoint, allow_remote=True)
        with self.assertRaises(ValueError):
            obs.configure(self.db, mode="opik", endpoint="https://opik.example/api")
        obs.configure(self.db, mode="opik", endpoint="https://opik.example/api", allow_remote=True)
        self.assertEqual(obs.settings(self.db)["mode"], "opik")

    def test_full_event_purge_clears_operational_log(self):
        obs.configure(self.db, mode="local")
        self.record()
        store = EventStore(self.db)
        try:
            store.delete_all(subject_id="synthetic")
        finally:
            store.close()
        self.assertEqual(obs.status(self.db)["records"], 0)

    def test_export_does_not_import_sdk_without_due_records(self):
        obs.configure(self.db, mode="opik", endpoint="http://localhost:5173/api")
        with patch("digital_twin_sensor.opik_exporter._sdk", side_effect=AssertionError("SDK imported")):
            self.assertEqual(export_once(self.db)["status"], "idle")


@unittest.skipUnless(importlib.util.find_spec("opik"), "Opik contract tests require the observability extra on Python 3.10+")
class OpikSDKTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "events.sqlite"
        self.requests = []
        self.nonlocal_attempts = []
        self.http_status = 204
        self.reject_spans = False
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, payload))
                code = 503 if fixture.reject_spans and "spans" in self.path else fixture.http_status
                self.send_response(code)
                self.end_headers()
                if code != 204:
                    self.wfile.write(b'{"message":"SERVER_SECRET_CANARY"}')

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.server.shutdown)
        obs.configure(self.db, mode="opik", endpoint=f"http://127.0.0.1:{self.server.server_port}/api")
        with obs.operation(self.db, "observability.test"):
            with obs.operation(self.db, "context.pack") as span:
                span.outcome("blocked")
                span.counts(deny=1)
        self.guard = patch.dict(os.environ, {"DTS_OPIK_API_KEY": "", "OPIK_API_KEY": "AMBIENT_SECRET_CANARY"})
        self.guard.start()
        self.addCleanup(self.guard.stop)
        original = socket.socket.connect

        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
                fixture.nonlocal_attempts.append(address[0])
                raise AssertionError("Unexpected non-local network connection")
            return original(sock, address)

        guard = patch.object(socket.socket, "connect", local_only)
        guard.start()
        self.addCleanup(guard.stop)

    def retry_now(self):
        with obs.connect(self.db) as conn:
            conn.execute("UPDATE records SET next_attempt=0")
            conn.commit()

    def test_real_sdk_serialization_no_content_and_acknowledgement(self):
        result = export_once(self.db)
        self.assertEqual(result, {"status": "accepted", "accepted": 1})
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.nonlocal_attempts, [])
        self.assertEqual(obs.status(self.db)["pending"], 0)
        wire = json.dumps(self.requests)
        self.assertNotIn("SECRET_CANARY", wire)
        self.assertNotIn('"input"', wire)
        self.assertNotIn('"output"', wire)
        self.assertNotIn("subject_id", wire)
        trace = self.requests[0][1]["traces"][0]
        span = self.requests[1][1]["spans"][0]
        self.assertEqual(uuid.UUID(trace["id"]).version, 7)
        self.assertEqual(span["trace_id"], trace["id"])
        self.assertEqual(span["metadata"]["outcome"], "blocked")
        self.assertEqual(os.environ["OPIK_SENTRY_ENABLE"], "false")
        self.assertEqual(os.environ["OPIK_ANALYTICS_ENABLE"], "false")

    def test_partial_failure_retries_same_ids_without_claiming_success(self):
        self.reject_spans = True
        self.assertEqual(export_once(self.db)["error"], "server")
        failed_id = self.requests[0][1]["traces"][0]["id"]
        state = obs.status(self.db)
        self.assertIsNone(state["exporter"]["last_success"])
        self.assertEqual(state["pending"], 1)
        self.assertNotIn("SERVER_SECRET_CANARY", json.dumps(state))
        count = len(self.requests)
        self.assertEqual(export_once(self.db)["status"], "idle")
        self.assertEqual(len(self.requests), count)
        self.retry_now()
        self.reject_spans = False
        self.assertEqual(export_once(self.db)["status"], "accepted")
        self.assertEqual(self.requests[2][1]["traces"][0]["id"], failed_id)

    def test_auth_failures_dead_letter_after_six_attempts(self):
        self.http_status = 401
        for _ in range(6):
            self.retry_now()
            self.assertEqual(export_once(self.db)["error"], "authentication")
        state = obs.status(self.db)
        self.assertEqual(state["pending"], 0)
        self.assertEqual(state["recent"][0]["delivery"], "failed")
        self.assertEqual(state["exporter"]["failures"], 6)

    def test_export_lease_and_disable_prevent_new_requests(self):
        with obs.connect(self.db) as conn:
            conn.execute("UPDATE exporter SET lease_until=?", (time.time()+120,))
            conn.commit()
        self.assertEqual(export_once(self.db)["status"], "busy")
        obs.configure(self.db, mode="off")
        self.assertEqual(export_once(self.db)["status"], "disabled")
        self.assertEqual(self.requests, [])
