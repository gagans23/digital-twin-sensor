import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from digital_twin_sensor.collectors.local_ocr import (
    active_ocr_surface_detail,
    ocr_detail_enabled,
    ocr_provider_status,
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

    def test_provider_status_requires_helper_for_macos_window_capture(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "digital_twin_sensor.collectors.local_ocr.platform.system",
            return_value="Darwin",
        ), patch(
            "digital_twin_sensor.collectors.local_ocr._helper_path",
            return_value=Path(tmp) / "missing-helper",
        ), patch(
            "digital_twin_sensor.collectors.local_ocr.shutil.which",
            return_value="/opt/homebrew/bin/tesseract",
        ):
            status = ocr_provider_status({"ocr_tesseract_binary": "tesseract"})

        providers = {item["name"]: item for item in status["providers"]}
        self.assertEqual(status["status"], "not_ready")
        self.assertEqual(providers["apple_vision"]["status"], "missing_helper")
        self.assertEqual(providers["tesseract"]["status"], "missing_helper")

    def test_provider_status_respects_tesseract_preference_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "macos-ocr-probe"
            helper.write_text("helper", encoding="utf-8")
            with patch(
                "digital_twin_sensor.collectors.local_ocr.platform.system",
                return_value="Darwin",
            ), patch(
                "digital_twin_sensor.collectors.local_ocr._helper_path",
                return_value=helper,
            ), patch(
                "digital_twin_sensor.collectors.local_ocr.shutil.which",
                return_value="/opt/homebrew/bin/tesseract",
            ):
                status = ocr_provider_status(
                    {"ocr_surface_provider": "tesseract", "ocr_tesseract_binary": "tesseract"}
                )

        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["preferred"], "tesseract")

    def test_tesseract_fallback_runs_after_empty_apple_vision(self):
        config = {
            "context_capture_depth": 4,
            "enable_ocr_surface_details": True,
            "ocr_surface_min_depth": 4,
            "ocr_surface_detail_apps": ["Ibo Pro Player"],
            "ocr_surface_provider": "apple_vision",
            "mask_pii": True,
            "mask_configured_names": True,
            "name_terms_to_mask": [],
        }
        calls = []

        def fake_probe(app, cfg, provider):
            calls.append(provider)
            if provider == "apple_vision":
                return {"status": "empty", "provider": provider, "lines": []}
            return {
                "status": "captured",
                "provider": "tesseract",
                "source": "tesseract_cli",
                "app": app,
                "line_count": 1,
                "lines": [{"text": "Trading lesson overlay", "confidence": 0.0}],
            }

        with patch(
            "digital_twin_sensor.collectors.local_ocr._run_macos_ocr_probe",
            Mock(side_effect=fake_probe),
        ):
            detail = active_ocr_surface_detail("Ibo Pro Player", config)

        self.assertEqual(calls, ["apple_vision", "tesseract"])
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["provider"], "tesseract")
        self.assertIn("Trading lesson overlay", detail["text_hints"])


if __name__ == "__main__":
    unittest.main()
