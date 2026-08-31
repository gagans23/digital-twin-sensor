import copy
import http.client
import io
import json
import tempfile
import threading
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from digital_twin_sensor.cli import cmd_collect_once, cmd_encrypt_store
from digital_twin_sensor.collectors.macos_active_window import build_event
from digital_twin_sensor.config import DEFAULT_CONFIG, load_config, write_config
from digital_twin_sensor.context_pack import build_context_pack
from digital_twin_sensor.learning import LearningStore, build_learning_state
from digital_twin_sensor.resume_study import find_resume_events, run_resume_study
from digital_twin_sensor.store import EventStore, open_event_store, utc_now
from digital_twin_sensor.synthesis import format_synthesis_markdown, synthesize_collective
from digital_twin_sensor.web import TwinDashboardHandler, TwinDashboardServer
from digital_twin_sensor.working_spheres import build_working_spheres

try:
    import cryptography
    CRYPTO = True
except ImportError:
    CRYPTO = False


def event(i=1, title="Synthetic gateway implementation", start=None, seconds=90):
    start = start or utc_now() - timedelta(minutes=20-i*2)
    return dict(id=i, subject_id="audit-subject", source="synthetic", app="Code",
                title=title, artifact=title, domain="coding", action="focus",
                ts_start=start.isoformat(), ts_end=(start+timedelta(seconds=seconds)).isoformat(),
                dwell_seconds=seconds, metadata={"redaction_findings": {}, "hint": "synthetic-private-hint"})


class SyntheticFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "events.sqlite"
        self.config_path = self.root / "config.json"
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.cfg["subject_id"] = "audit-subject"
        write_config(self.cfg, self.config_path)


class HardeningTests(SyntheticFixture):
    def test_disabled_titles_never_reach_structured_connector(self):
        self.cfg.update(capture_window_title=False, context_capture_depth=1)
        with patch("digital_twin_sensor.collectors.macos_active_window.active_window",
                   return_value=("Visual Studio Code", "private-project - Visual Studio Code")):
            captured = build_event(self.cfg, 15)
        self.assertNotIn("private-project", json.dumps(captured))

    def test_purge_all_removes_cards_and_feedback_even_when_events_are_gone(self):
        events = [event()]
        pack = build_context_pack(events, self.cfg, target="local_file")
        build_learning_state(events, self.cfg, subject_id=self.cfg["subject_id"], db_path=self.db)
        learning = LearningStore(self.db)
        learning.add_feedback(subject_id=self.cfg["subject_id"], pack_id=pack["pack_id"],
                              sphere_id=pack["selected_sphere_id"], label="too_private", config=self.cfg)
        learning.close()
        store = EventStore(self.db)
        self.assertEqual(store.delete_all(subject_id=self.cfg["subject_id"]), 0)
        store.close()
        state = build_learning_state([], self.cfg, subject_id=self.cfg["subject_id"], db_path=self.db)
        self.assertEqual(state["cards"], [])
        self.assertEqual(state["stats"]["feedback_count"], 0)

    def test_empty_window_removes_cached_cards(self):
        build_learning_state([event()], self.cfg, subject_id=self.cfg["subject_id"], db_path=self.db)
        state = build_learning_state([], self.cfg, subject_id=self.cfg["subject_id"], db_path=self.db)
        self.assertEqual(state["cards"], [])

    def test_privacy_feedback_blocks_next_pack_until_explicit_resolution(self):
        events = [event(), event(2)]
        before = build_context_pack(events, self.cfg, target="local_file", db_path=self.db)
        store = LearningStore(self.db)
        saved = store.add_feedback(subject_id=self.cfg["subject_id"], pack_id=before["pack_id"],
                                   sphere_id=before["selected_sphere_id"], label="too_private", config=self.cfg)
        blocked = build_context_pack(events, self.cfg, target="codex", db_path=self.db)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["context"], {})
        self.assertNotIn(events[0]["artifact"], blocked["export"]["markdown"])
        store.resolve_feedback(subject_id=self.cfg["subject_id"], feedback_id=saved["id"])
        store.close()
        self.assertEqual(build_context_pack(events, self.cfg, target="codex", db_path=self.db)["status"], "ready")

    def test_legacy_privacy_feedback_does_not_disappear_after_regrouping(self):
        pack = build_context_pack([event()], self.cfg, target="local_file", feedback=[
            {"sphere_id": "old-identity", "label": "too_private", "pack_id": "old-pack"}])
        self.assertEqual(pack["status"], "blocked")

    def test_suppression_output_never_names_private_topic_or_small_count(self):
        sphere = dict(label="Confidential Cedar acquisition", domain="strategy", events=1, dwell_seconds=15)
        result = synthesize_collective([{"subject_key": "person", "activities": {"spheres": [sphere]}}])
        blob = json.dumps(result) + format_synthesis_markdown(result)
        self.assertNotIn("cedar", blob.lower())
        self.assertNotIn("acquisition", blob.lower())
        self.assertNotIn("subjects", result["withheld"][0])

    def test_sensitive_spheres_never_clear_aggregation_floor(self):
        sphere = dict(label="Cedar acquisition", domain="strategy", sensitivity="high", events=1)
        bundles = [{"subject_key": str(i), "activities": {"spheres": [sphere]}} for i in range(6)]
        self.assertEqual(synthesize_collective(bundles)["themes"], [])

    def test_unrelated_projects_do_not_merge_from_app_and_category(self):
        events = [event(1, "Cedar finance backend", utc_now()-timedelta(days=2)),
                  event(2, "Juniper video renderer", utc_now()-timedelta(hours=1))]
        self.assertEqual(len(build_working_spheres(events, self.cfg)["spheres"]), 2)

    def test_same_artifact_identity_survives_window_rollover(self):
        events = [event(), event(2)]
        before = build_working_spheres(events, self.cfg)["spheres"][0]["id"]
        after = build_working_spheres(events[1:], self.cfg)["spheres"][0]["id"]
        self.assertEqual(before, after)

    def test_unknown_purpose_is_rejected(self):
        for purpose in ("", "unknown"):
            with self.assertRaises(ValueError):
                build_context_pack([event()], self.cfg, purpose=purpose)

    def test_continuous_detour_is_detected_without_claiming_pack_exposure(self):
        base = utc_now() - timedelta(hours=3)
        events = [event(1, "Task alpha", base, 120),
                  event(2, "Task beta", base+timedelta(seconds=120), 1200),
                  event(3, "Task alpha", base+timedelta(seconds=1320), 120)]
        self.assertEqual(len(find_resume_events(events)), 1)
        report = run_resume_study(events)
        self.assertFalse(report["comparable"])
        self.assertIsNone(report["comparison"])

    @unittest.skipUnless(CRYPTO, "encryption extra not installed")
    def test_migration_then_normal_collection_encrypts_events_and_learning(self):
        store = EventStore(self.db)
        store.insert_event(event())
        self.addCleanup(store.close)
        build_learning_state([event()], self.cfg, subject_id=self.cfg["subject_id"], db_path=self.db)
        with patch("digital_twin_sensor.crypto._load_from_keyring", return_value=None), \
             patch("digital_twin_sensor.crypto._store_in_keyring", return_value=False), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cmd_encrypt_store(Namespace(config=self.config_path, db=self.db, status=False)), 0)
            with patch("digital_twin_sensor.cli.build_event", return_value=event(2)):
                cmd_collect_once(Namespace(config=self.config_path, db=self.db, dwell_seconds=15))
        with self.assertRaises(RuntimeError):
            store.insert_event(event(3))
        store.close()
        cfg = load_config(self.config_path)
        self.assertTrue(cfg["encrypt_at_rest"])
        store = open_event_store(self.db, cfg)
        self.assertEqual(len(store.fetch_events()), 2)
        store.close()
        raw = self.db.read_bytes()
        self.assertNotIn(b"Synthetic gateway implementation", raw)
        self.assertNotIn(b"synthetic-private-hint", raw)
        learning = LearningStore(self.db, config=cfg)
        self.assertEqual(len(learning.list_cards(subject_id=cfg["subject_id"])), 1)
        learning.close()

    def test_missing_encryption_key_fails_closed(self):
        self.cfg["encrypt_at_rest"] = True
        with patch("digital_twin_sensor.crypto._load_from_keyring", return_value=None):
            with self.assertRaises(RuntimeError):
                open_event_store(self.db, self.cfg)
        self.assertFalse(self.db.with_suffix(".key").exists())


class DashboardBoundaryTests(SyntheticFixture):
    def setUp(self):
        super().setUp()
        self.server = TwinDashboardServer(("127.0.0.1", 0), TwinDashboardHandler)
        self.server.db_path, self.server.config_path, self.server.verbose = self.db, self.config_path, False
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, *, authenticated=False, headers=None, payload=None):
        request_headers = dict(headers or {})
        if authenticated:
            request_headers["X-DTS-Token"] = self.server.session_token
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=request_headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_asset_traversal_is_rejected(self):
        for path in ("/assets/../config.py", "/assets/%2e%2e/config.py", "/assets//etc/passwd"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_untrusted_host_and_origin_cannot_pause(self):
        for headers in ({"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"}):
            self.assertEqual(self.request("POST", "/api/admin/pause", authenticated=True, headers=headers)[0], 403)
        self.assertFalse(load_config(self.config_path)["collection_paused"])

    def test_api_requires_session_but_page_bootstraps_it(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.server.session_token.encode(), body)
        self.assertEqual(self.request("GET", "/api/events")[0], 403)
        self.assertEqual(self.request("POST", "/api/admin/pause")[0], 403)
        self.assertEqual(self.request("POST", "/api/admin/pause", authenticated=True)[0], 200)
        self.assertTrue(load_config(self.config_path)["collection_paused"])

    def test_network_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            TwinDashboardServer(("0.0.0.0", 0), TwinDashboardHandler)

    def test_observability_requires_session_and_cannot_enable_external_export(self):
        self.assertEqual(self.request("GET", "/api/observability")[0], 403)
        self.assertEqual(self.request("POST", "/api/observability", payload={"action": "local"})[0], 403)
        self.assertEqual(self.request("POST", "/api/observability", authenticated=True, payload={"action": "opik", "endpoint": "https://example.com"})[0], 400)
        status, body = self.request("POST", "/api/observability", authenticated=True, payload={"action": "local"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "local")
        self.assertEqual(self.request("POST", "/api/observability", authenticated=True, payload={"action": "test"})[0], 200)
        status, body = self.request("GET", "/api/observability", authenticated=True)
        self.assertEqual(json.loads(body)["records"], 1)

    def test_empty_or_unknown_purpose_is_a_bad_request(self):
        for purpose in ("", "unknown"):
            status, _ = self.request("GET", "/api/context-pack?purpose=" + purpose, authenticated=True)
            self.assertEqual(status, 400)

    def test_resume_routes_require_session_and_validate_actions(self):
        self.assertEqual(self.request("GET", "/api/resume")[0], 403)
        self.assertEqual(self.request("POST", "/api/resume")[0], 403)
        self.assertEqual(self.request("GET", "/api/resume", authenticated=True)[0], 200)
        self.assertEqual(self.request("POST", "/api/resume", authenticated=True, payload={"action":"invalid"})[0], 400)

    def test_resume_checkpoint_http_path_and_conflict(self):
        store = EventStore(self.db)
        store.insert_event(event())
        store.close()
        status, body = self.request("GET", "/api/resume", authenticated=True)
        self.assertEqual(status, 200)
        view = json.loads(body)
        payload = {"action":"checkpoint", "sphere_id":view["selected_sphere_id"], "state":"Synthetic checkpoint"}
        self.assertEqual(self.request("POST", "/api/resume", authenticated=True, payload=payload)[0], 200)
        self.assertEqual(self.request("POST", "/api/resume", authenticated=True, payload=payload)[0], 409)
