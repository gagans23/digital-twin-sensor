import json
import unittest

from digital_twin_sensor.collectors.accessibility_surface import (
    accessibility_detail_enabled,
    sanitize_accessibility_surface_detail,
)


class AccessibilitySurfaceTests(unittest.TestCase):
    def test_depth_and_allowlist_gate_accessibility_capture(self):
        config = {
            "context_capture_depth": 2,
            "enable_accessibility_surface_details": True,
            "accessibility_surface_min_depth": 3,
            "accessibility_surface_detail_apps": ["Ibo Pro Player"],
        }

        self.assertFalse(accessibility_detail_enabled("Ibo Pro Player", config))
        config["context_capture_depth"] = 3
        self.assertTrue(accessibility_detail_enabled("Ibo Pro Player", config))
        self.assertFalse(accessibility_detail_enabled("Safari", config))

    def test_sanitizes_ui_labels_before_storage(self):
        detail = {
            "app": "Ibo Pro Player",
            "elements": [
                {"role": "AXStaticText", "name": "Champions League Live", "value": ""},
                {"role": "AXStaticText", "name": "Gagan Sachdeva", "value": ""},
                {"role": "AXTextField", "name": "Card", "value": "4111 1111 1111 1111"},
            ],
        }
        config = {
            "mask_pii": True,
            "mask_configured_names": True,
            "mask_ip_addresses": True,
            "name_terms_to_mask": ["Gagan", "Sachdeva"],
            "accessibility_surface_text_limit": 96,
            "accessibility_surface_max_hints": 10,
        }

        safe = sanitize_accessibility_surface_detail(detail, config)
        payload = json.dumps(safe)

        self.assertEqual(safe["kind"], "accessibility_snapshot")
        self.assertEqual(safe["status"], "captured")
        self.assertIn("Champions League Live", safe["text_hints"])
        self.assertIn("[name]", payload)
        self.assertIn("[credit-card]", payload)
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("4111", payload)


if __name__ == "__main__":
    unittest.main()
