import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from digital_twin_sensor.collectors.macos_active_window import build_event
from digital_twin_sensor.config import load_config, write_config
from digital_twin_sensor.store import EventStore, utc_now


def sample_event(ts, title="Research"):
    return {
        "subject_id": "local-user",
        "source": "test",
        "app": "Safari",
        "title": title,
        "artifact": title,
        "domain": "browser-research",
        "action": "focus",
        "ts_start": ts.isoformat(),
        "ts_end": (ts + timedelta(seconds=15)).isoformat(),
        "dwell_seconds": 15.0,
        "metadata": {"redaction_findings": {}},
    }


class ControlTests(unittest.TestCase):
    def test_paused_collection_builds_no_event(self):
        config = {"collection_paused": True, "subject_id": "local-user"}
        with patch("digital_twin_sensor.collectors.macos_active_window.active_window") as active:
            event = build_event(config, 15.0)
        self.assertIsNone(event)
        active.assert_not_called()

    def test_retention_delete_removes_only_old_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "events.sqlite"
            store = EventStore(db)
            old_ts = utc_now() - timedelta(days=45)
            recent_ts = utc_now() - timedelta(days=2)
            store.insert_event(sample_event(old_ts, "Old"))
            store.insert_event(sample_event(recent_ts, "Recent"))

            cutoff = utc_now() - timedelta(days=30)
            self.assertEqual(store.count_before(subject_id="local-user", cutoff=cutoff), 1)
            self.assertEqual(store.delete_before(subject_id="local-user", cutoff=cutoff), 1)
            self.assertEqual(store.count_events(subject_id="local-user"), 1)
            store.close()

    def test_write_config_persists_pause_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            write_config({"subject_id": "local-user", "collection_paused": True}, config_path)
            self.assertTrue(load_config(config_path)["collection_paused"])


if __name__ == "__main__":
    unittest.main()
