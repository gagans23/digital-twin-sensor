import unittest

from digital_twin_sensor.web import _attention_depth_payload, _surface_details


def event(app, title, detail=None):
    return {
        "id": 1,
        "subject_id": "local-user",
        "source": "macos_active_window",
        "app": app,
        "title": title,
        "artifact": title,
        "domain": "other",
        "action": "focus",
        "ts_start": "2026-08-28T08:00:00+00:00",
        "ts_end": "2026-08-28T08:00:15+00:00",
        "dwell_seconds": 15.0,
        "metadata": {"surface_detail": detail, "redaction_findings": {}},
    }


class AttentionDepthTests(unittest.TestCase):
    def test_marks_player_as_opaque_until_detail_capture(self):
        config = {
            "context_capture_depth": 2,
            "enable_browser_tab_details": True,
            "browser_tab_detail_min_depth": 2,
            "browser_tab_detail_apps": ["Safari", "Google Chrome"],
            "enable_accessibility_surface_details": True,
            "accessibility_surface_min_depth": 3,
            "accessibility_surface_detail_apps": ["Ibo Pro Player"],
        }
        events = [event("Ibo Pro Player", "Ibo Pro Player")]
        surfaces = _surface_details(events, config)
        payload = _attention_depth_payload(events, config, surfaces)

        self.assertEqual(payload["media_focus"]["status"], "opaque")
        self.assertEqual(payload["media_focus"]["playback_visibility"], "app/window only")
        self.assertTrue(
            any(item["name"] == "Deepen opaque player apps" for item in payload["recommendations"])
        )

    def test_treats_accessibility_snapshot_as_rich_detail(self):
        detail = {
            "kind": "accessibility_snapshot",
            "status": "captured",
            "app": "Ibo Pro Player",
            "element_count": 4,
            "roles": [{"role": "AXStaticText", "count": 2}],
            "text_hints": ["Match replay", "Channel 4"],
            "redaction_findings": {},
            "privacy": "allowlisted Accessibility metadata",
        }
        config = {
            "context_capture_depth": 3,
            "enable_browser_tab_details": True,
            "browser_tab_detail_min_depth": 2,
            "browser_tab_detail_apps": ["Safari", "Google Chrome"],
            "enable_accessibility_surface_details": True,
            "accessibility_surface_min_depth": 3,
            "accessibility_surface_detail_apps": ["Ibo Pro Player"],
        }
        events = [event("Ibo Pro Player", "Ibo Pro Player", detail)]
        surfaces = _surface_details(events, config)
        payload = _attention_depth_payload(events, config, surfaces)

        self.assertEqual(surfaces[0]["status"], "in-app surface captured")
        self.assertEqual(payload["application_attention"][0]["status"], "rich")
        self.assertEqual(payload["media_focus"]["status"], "captured")
        self.assertEqual(payload["media_focus"]["playback_visibility"], "allowlisted UI metadata")


if __name__ == "__main__":
    unittest.main()
