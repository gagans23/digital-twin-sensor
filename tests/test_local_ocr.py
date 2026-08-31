import json
import unittest

from digital_twin_sensor.collectors.local_ocr import (
    ocr_detail_enabled,
    sanitize_ocr_surface_detail,
)


class LocalOcrTests(unittest.TestCase):
    def test_depth_and_allowlist_gate_ocr_capture(self):
        config = {
            "context_capture_depth": 3,
            "enable_ocr_surface_details": True,
            "ocr_surface_min_depth": 4,
            "ocr_surface_detail_apps": ["Ibo Pro Player"],
        }

        self.assertFalse(ocr_detail_enabled("Ibo Pro Player", config))
        config["context_capture_depth"] = 4
        self.assertTrue(ocr_detail_enabled("Ibo Pro Player", config))
        self.assertFalse(ocr_detail_enabled("Safari", config))

    def test_sanitizes_ocr_lines_before_storage(self):
        detail = {
            "provider": "apple_vision",
            "source": "VNRecognizeTextRequest",
            "app": "Ibo Pro Player",
            "window_title": "Gagan private replay",
            "line_count": 3,
            "lines": [
                {"text": "Trading psychology module", "confidence": 0.91},
                {"text": "Gagan Sachdeva", "confidence": 0.88},
                {"text": "Card 4111 1111 1111 1111", "confidence": 0.82},
            ],
        }
        config = {
            "mask_pii": True,
            "mask_configured_names": True,
            "mask_ip_addresses": True,
            "name_terms_to_mask": ["Gagan", "Sachdeva"],
            "ocr_surface_max_lines": 12,
            "ocr_surface_max_hints": 8,
            "ocr_surface_text_limit": 120,
        }

        safe = sanitize_ocr_surface_detail(detail, config)
        payload = json.dumps(safe)

        self.assertEqual(safe["kind"], "ocr_summary")
        self.assertEqual(safe["status"], "captured")
        self.assertEqual(safe["provider"], "apple_vision")
        self.assertIn("Trading psychology module", safe["text_hints"])
        self.assertIn("[name]", payload)
        self.assertIn("[credit-card]", payload)
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("4111", payload)
        self.assertNotIn("lines", safe)
        self.assertNotIn("box", payload)


if __name__ == "__main__":
    unittest.main()
