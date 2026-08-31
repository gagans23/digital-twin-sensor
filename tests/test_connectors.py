"""Structured App Connectors v1.

The tests that matter here are the negative ones. Anyone can check that a
connector extracts a title; the contract worth defending is that it cannot
extract anything else, cannot read a source the user has not enabled, and
cannot reach for OCR when a cheaper source already answered.
"""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from digital_twin_sensor.config import DEFAULT_CONFIG
from digital_twin_sensor.connectors import (
    ManifestError,
    apply_connector,
    connector_for_app,
    load_manifests,
    parse_manifest,
    registry,
    registry_summary,
    structured_detail,
)
from digital_twin_sensor.connectors.manifest import MANIFEST_DIR


def cfg(depth=4, **over):
    config = deepcopy(DEFAULT_CONFIG)
    config["context_capture_depth"] = depth
    config.update(over)
    return config


class ManifestValidationTests(unittest.TestCase):
    def test_every_shipped_manifest_loads(self):
        manifests = load_manifests()
        self.assertGreaterEqual(len(manifests), 3)

    def test_shipped_manifests_are_valid_json_and_named_for_their_id(self):
        for path in sorted(MANIFEST_DIR.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.stem, payload["id"], f"{path.name} filename should match its id")

    def test_every_field_is_documented(self):
        """A field nobody described is a field nobody reviewed."""
        for manifest in load_manifests():
            for spec in manifest.fields:
                self.assertTrue(spec.description.strip(), f"{manifest.id}.{spec.name} has no description")

    def test_every_manifest_declares_what_it_refuses(self):
        for manifest in load_manifests():
            self.assertTrue(manifest.denied, f"{manifest.id} declares nothing denied")

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ManifestError):
            parse_manifest({"id": "x", "apps": [], "min_depth": 1, "sources": ["screenshots"],
                            "fields": [{"name": "a", "store": "redacted", "from": "t"}]})

    def test_undeclared_graph_field_is_rejected(self):
        with self.assertRaises(ManifestError):
            parse_manifest({"id": "x", "apps": [], "min_depth": 1, "sources": ["window_title"],
                            "fields": [{"name": "a", "store": "redacted", "from": "t"}],
                            "graph": {"label_field": "not_declared"}})


class AllowlistEnforcementTests(unittest.TestCase):
    """The central claim of this layer."""

    def test_undeclared_fields_in_a_surface_are_never_stored(self):
        manifest = connector_for_app("Safari")
        out = apply_connector(manifest, {"browser_tab": {
            "title": "Quarterly review",
            "url_domain": "example.com",
            "url_path": "/secret/path",          # not declared
            "url_query": "token=abc123",         # not declared
            "cookies": "session=xyz",            # not declared
            "page_body": "the entire document",  # not declared
        }}, cfg(2))
        self.assertIn("page_title", out["fields"])
        for forbidden in ("url_path", "url_query", "cookies", "page_body"):
            self.assertNotIn(forbidden, out["fields"])
        blob = json.dumps(out)
        self.assertNotIn("/secret/path", blob)
        self.assertNotIn("token=abc123", blob)
        self.assertNotIn("session=xyz", blob)

    def test_output_keys_are_a_subset_of_the_manifest(self):
        for manifest in registry():
            out = apply_connector(manifest, {
                src: {"title": "x", "summary": "x", "text_hints": ["x"], "url_domain": "x", "junk": "x"}
                for src in manifest.sources
            }, cfg(4))
            self.assertTrue(set(out["fields"]) <= set(manifest.field_names))


class DepthTests(unittest.TestCase):
    def test_connector_below_its_depth_captures_nothing(self):
        out = structured_detail("Ibo Pro Player", {"accessibility": {"text_hints": ["Playing"]}}, cfg(2))
        self.assertEqual(out["status"], "below_depth")
        self.assertEqual(out["fields"], {})

    def test_a_source_above_current_depth_is_never_read(self):
        """OCR data present in the surfaces map must be ignored at depth 3."""
        out = structured_detail("Ibo Pro Player", {
            "accessibility": {"text_hints": []},
            "ocr": {"text_hints": ["Lesson 9 Secret Title"], "summary": "Lesson 9 Secret Title"},
        }, cfg(3))
        self.assertNotIn("ocr", out["sources_permitted"])
        self.assertNotIn("Lesson 9 Secret Title", json.dumps(out))

    def test_disabling_connectors_disables_them(self):
        self.assertIsNone(structured_detail("Safari", {"browser_tab": {"title": "x"}},
                                            cfg(4, enable_structured_connectors=False)))


class MediaPlayerConnectorTests(unittest.TestCase):
    def test_extracts_title_state_and_position_from_accessibility(self):
        out = structured_detail("Ibo Pro Player", {"accessibility": {
            "text_hints": ["Module 3: Context Engineering", "Playing", "12:04"]}}, cfg(4))
        self.assertEqual(out["status"], "captured")
        self.assertEqual(out["fields"]["playback_state"], "playing")
        self.assertEqual(out["fields"]["position"], "12:04")
        self.assertIn("Context Engineering", out["fields"]["media_title"])

    def test_ocr_is_not_consulted_when_accessibility_answers(self):
        """The reason this connector exists: fewer OCR invocations, not more."""
        out = structured_detail("Ibo Pro Player", {
            "accessibility": {"text_hints": ["Module 3: Context Engineering", "Playing", "12:04"]},
            "ocr": {"summary": "OCR SHOULD NOT BE READ", "text_hints": ["OCR SHOULD NOT BE READ"]},
        }, cfg(4))
        self.assertEqual(out["sources_consulted"], ["accessibility"])
        self.assertIn("ocr", out["sources_not_needed"])
        self.assertNotIn("OCR SHOULD NOT BE READ", json.dumps(out))

    def test_falls_back_to_ocr_with_lower_confidence(self):
        out = structured_detail("Ibo Pro Player", {
            "accessibility": {"text_hints": []},
            "ocr": {"summary": "Lesson 7 Attention Filters", "text_hints": ["Lesson 7 Attention Filters", "Paused"]},
        }, cfg(4))
        self.assertEqual(out["provenance"]["media_title"], "ocr")
        self.assertLess(out["confidence"], 0.6)


class BrowserPageConnectorTests(unittest.TestCase):
    def test_keeps_domain_and_title_only(self):
        out = structured_detail("Safari", {"browser_tab": {
            "title": "Pull request #42", "url_domain": "github.com"}}, cfg(2))
        self.assertEqual(out["fields"]["domain"], "github.com")
        self.assertEqual(out["fields"]["page_kind"], "pull request")

    def test_domain_mode_strips_anything_path_like(self):
        out = structured_detail("Safari", {"browser_tab": {
            "title": "x", "url_domain": "example.com/private/thing"}}, cfg(2))
        self.assertEqual(out["fields"]["domain"], "example.com")

    def test_pii_in_a_title_is_masked_before_storage(self):
        out = structured_detail("Safari", {"browser_tab": {
            "title": "mail to gagan.test@example.com", "url_domain": "mail.example.com"}}, cfg(2))
        self.assertNotIn("gagan.test@example.com", json.dumps(out))
        self.assertTrue(out["redaction_findings"])


class DevWorkspaceConnectorTests(unittest.TestCase):
    def test_reads_repo_and_file_from_the_window_title(self):
        out = structured_detail("Kiro", {"window_title": {
            "title": "registry.py — digital-twin-sensor — Kiro"}}, cfg(1))
        self.assertEqual(out["fields"]["active_file"], "registry.py")
        self.assertEqual(out["fields"]["repo"], "digital-twin-sensor")

    def test_counts_changed_files_without_listing_them(self):
        out = structured_detail("Kiro", {"window_title": {"title": "repo — 7 changed — Kiro"}}, cfg(1))
        self.assertEqual(out["fields"]["dirty_files"], 7)
        self.assertIsInstance(out["fields"]["dirty_files"], int)

    def test_never_declares_a_field_for_file_contents(self):
        manifest = connector_for_app("Kiro")
        self.assertNotIn("file_contents", manifest.field_names)
        self.assertIn("file_contents", manifest.denied)


class SummaryTests(unittest.TestCase):
    def test_summary_reports_active_state_against_current_depth(self):
        rows = {r["id"]: r for r in registry_summary(cfg(2))}
        self.assertTrue(rows["browser_page"]["active"])
        self.assertFalse(rows["media_player"]["active"], "media needs depth 3")

    def test_summary_exposes_denied_lists_for_the_dashboard(self):
        for row in registry_summary(cfg(4)):
            self.assertTrue(row["denied"])
            self.assertTrue(row["fields"])


if __name__ == "__main__":
    unittest.main()


class DashboardContractTests(unittest.TestCase):
    """The dashboard is the consent surface. If it stops showing what a
    connector may store, the person being observed loses the only view they
    have -- so the payload shape is a contract, not an implementation detail."""

    def test_privacy_payload_carries_registry_and_activity(self):
        from digital_twin_sensor.web import _connector_activity

        activity = _connector_activity([{
            "metadata": {"structured": {
                "status": "captured", "connector": "media_player",
                "display_name": "Media player",
                "fields": {"media_title": "A"},
                "provenance": {"media_title": "accessibility"},
                "field_confidence": {"media_title": 0.8},
                "confidence": 0.8,
                "sources_not_needed": ["ocr"],
                "redaction_findings": {},
            }}
        }])
        self.assertEqual(activity["captured_events"], 1)
        self.assertEqual(activity["provenance_counts"]["accessibility"], 1)
        self.assertEqual(activity["costlier_sources_avoided"]["ocr"], 1)
        self.assertTrue(activity["explainer"])

    def test_activity_ignores_events_without_structured_output(self):
        from digital_twin_sensor.web import _connector_activity

        activity = _connector_activity([{"metadata": {}}, {"metadata": {"structured": None}}])
        self.assertEqual(activity["captured_events"], 0)

    def test_dashboard_markup_has_the_mount_points_the_renderer_writes_to(self):
        ui = Path("digital_twin_sensor/ui_static/index.html").read_text(encoding="utf-8")
        js = Path("digital_twin_sensor/ui_static/app.js").read_text(encoding="utf-8")
        for element_id in ("connectorRegistry", "connectorActivity"):
            self.assertIn(f'id="{element_id}"', ui, f"{element_id} missing from the dashboard")
            self.assertIn(f'$("{element_id}")', js, f"{element_id} never populated by app.js")


class GraphNormalizationTests(unittest.TestCase):
    def test_structured_fields_become_typed_graph_nodes_with_provenance(self):
        from datetime import timedelta

        from digital_twin_sensor.context_graph import build_context_graph
        from digital_twin_sensor.store import utc_now

        now = utc_now()
        events = [{
            "id": 1, "subject_id": "t", "source": "t", "app": "Ibo Pro Player",
            "title": "player", "artifact": "player", "domain": "media", "action": "focus",
            "ts_start": (now - timedelta(minutes=5)).isoformat(), "ts_end": now.isoformat(),
            "dwell_seconds": 300.0,
            "metadata": {"structured": {
                "status": "captured", "connector": "media_player",
                "fields": {"media_title": "Attention Filters"},
                "provenance": {"media_title": "accessibility"},
                "field_confidence": {"media_title": 0.8},
            }},
        }]
        graph = build_context_graph(events, cfg(4), days=14)
        nodes = [n for n in graph["nodes"] if n["type"] == "connector-field"]
        self.assertTrue(nodes, "structured fields did not reach the graph")
        self.assertIn("accessibility", nodes[0]["gate_reason"])

    def test_empty_structured_output_adds_no_nodes(self):
        from datetime import timedelta

        from digital_twin_sensor.context_graph import build_context_graph
        from digital_twin_sensor.store import utc_now

        now = utc_now()
        events = [{
            "id": 1, "subject_id": "t", "source": "t", "app": "Safari",
            "title": "page", "artifact": "page", "domain": "browser", "action": "focus",
            "ts_start": (now - timedelta(minutes=5)).isoformat(), "ts_end": now.isoformat(),
            "dwell_seconds": 60.0,
            "metadata": {"structured": {"status": "empty", "fields": {}}},
        }]
        graph = build_context_graph(events, cfg(4), days=14)
        self.assertFalse([n for n in graph["nodes"] if n["type"] == "connector-field"])
