import json
import unittest
from datetime import timedelta
from pathlib import Path

from digital_twin_sensor.fleet import build_fleet_status
from digital_twin_sensor.store import utc_now


class FleetTests(unittest.TestCase):
    def test_builds_local_device_status(self):
        now = utc_now()
        start = now - timedelta(seconds=15)
        events = [
            {
                "id": 1,
                "subject_id": "Gagan Sachdeva",
                "source": "macos_active_window",
                "app": "Safari",
                "title": "Research",
                "artifact": "Research",
                "domain": "browser-research",
                "action": "focus",
                "ts_start": start.isoformat(),
                "ts_end": now.isoformat(),
                "dwell_seconds": 15.0,
                "metadata": {"redaction_findings": {}},
            }
        ]
        config = {
            "context_capture_depth": 2,
            "fleet_device_id": "device_test",
            "fleet_device_name": "Test endpoint",
            "fleet_policy_version": "test-policy",
            "fleet_upload_mode": "summaries_only",
            "fleet_sync_enabled": False,
            "fleet_raw_event_upload": False,
            "fleet_allowed_export_targets": ["local_file", "kiro"],
            "mask_pii": True,
            "redact_url_paths": True,
            "enable_browser_tab_details": True,
            "browser_tab_detail_min_depth": 2,
            "browser_tab_store_url_path": False,
            "browser_tab_store_query": False,
            "enable_working_spheres": True,
            "enable_context_graph": True,
        }

        result = build_fleet_status(
            events,
            config,
            db_path=Path("/tmp/missing-events.sqlite"),
            days=1,
            total_count=1,
            collector_status={"installed": True, "state": "running", "pid": "1"},
            dashboard_status={"installed": True, "state": "running", "pid": "2"},
        )

        self.assertEqual(result["status"], "local-only")
        self.assertEqual(result["devices"][0]["id"], "device_test")
        self.assertEqual(result["devices"][0]["name"], "Test endpoint")
        self.assertEqual(result["devices"][0]["health"], "online")
        self.assertEqual(result["active_policy"]["version"], "test-policy")
        self.assertEqual(result["summary"]["blocking_count"], 0)
        self.assertNotIn("Gagan", json.dumps(result))

    def test_raw_event_upload_blocks_enterprise_readiness(self):
        result = build_fleet_status(
            [],
            {
                "fleet_device_id": "device_test",
                "fleet_raw_event_upload": True,
                "mask_pii": True,
                "browser_tab_store_url_path": False,
                "browser_tab_store_query": False,
                "fleet_allowed_export_targets": [],
            },
            db_path=Path("/tmp/missing-events.sqlite"),
            days=1,
            total_count=0,
            collector_status={"installed": True, "state": "running", "pid": "1"},
            dashboard_status={"installed": True, "state": "running", "pid": "2"},
        )

        raw_upload = [
            item
            for item in result["sync_readiness"]
            if item["name"] == "Raw event upload"
        ][0]
        self.assertEqual(raw_upload["status"], "blocked")
        self.assertGreater(result["summary"]["blocking_count"], 0)


if __name__ == "__main__":
    unittest.main()
