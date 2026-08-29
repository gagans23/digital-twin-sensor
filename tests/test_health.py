import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from digital_twin_sensor.health import build_health_report, run_watchdog
from digital_twin_sensor.store import EventStore, utc_now


class HealthTests(unittest.TestCase):
    def test_builds_health_report_without_raw_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "events.sqlite"
            config = root / "config.json"
            config.write_text(
                """
{
  "subject_id": "local-user",
  "sample_interval_seconds": 15,
  "context_capture_depth": 3,
  "mask_pii": true,
  "browser_tab_store_url_path": false,
  "browser_tab_store_query": false,
  "fleet_raw_event_upload": false,
  "enable_browser_tab_details": true,
  "browser_tab_detail_min_depth": 2,
  "browser_tab_detail_apps": ["Safari"],
  "enable_accessibility_surface_details": true,
  "accessibility_surface_min_depth": 3,
  "accessibility_surface_detail_apps": ["Ibo Pro Player"]
}
""".strip()
                + "\n",
                encoding="utf-8",
            )
            store = EventStore(db)
            end = utc_now()
            start = end - timedelta(seconds=15)
            store.insert_event(
                {
                    "subject_id": "local-user",
                    "source": "test",
                    "app": "Safari",
                    "title": "Research",
                    "artifact": "Research",
                    "domain": "browser-research",
                    "action": "focus",
                    "ts_start": start.isoformat(),
                    "ts_end": end.isoformat(),
                    "dwell_seconds": 15.0,
                    "metadata": {"redaction_findings": {}},
                }
            )
            store.close()

            with patch(
                "digital_twin_sensor.health.service_status",
                return_value={"installed": True, "state": "running", "pid": "1"},
            ), patch(
                "digital_twin_sensor.health.active_window",
                return_value=("Safari", "Research"),
            ):
                report = build_health_report(db_path=db, config_path=config)

        self.assertEqual(report["summary"]["capture_depth"], 3)
        self.assertTrue(report["diagnostics"])
        self.assertTrue(report["beyond_paper"])
        self.assertTrue(report["paper_deviations"])
        self.assertTrue(report["research_backlog"])
        self.assertLessEqual(report["last_event"]["last_age_seconds"], 5)

    def test_watchdog_restarts_stale_collector_when_fix_enabled(self):
        stale_report = {
            "status": "attention",
            "services": {
                "collector": {"installed": True, "state": "running", "pid": "1"},
                "dashboard": {"installed": True, "state": "running", "pid": "2"},
            },
            "last_event": {"last_age_seconds": 999},
        }
        fresh_report = {
            "status": "ready",
            "services": {
                "collector": {"installed": True, "state": "running", "pid": "1"},
                "dashboard": {"installed": True, "state": "running", "pid": "2"},
            },
            "last_event": {"last_age_seconds": 1},
        }
        with patch(
            "digital_twin_sensor.health.build_health_report",
            side_effect=[stale_report, fresh_report],
        ), patch(
            "digital_twin_sensor.health.kickstart_service",
            return_value={"service": "com.local.digital-twin-sensor", "status": "restarted"},
        ) as kickstart:
            result = run_watchdog(
                db_path=Path("/tmp/events.sqlite"),
                config_path=Path("/tmp/config.json"),
                stale_after_seconds=180,
                fix=True,
            )

        self.assertTrue(result["fixed"])
        self.assertEqual(result["report"]["status"], "ready")
        kickstart.assert_called_once()


if __name__ == "__main__":
    unittest.main()
