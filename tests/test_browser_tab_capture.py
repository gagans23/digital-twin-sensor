import unittest
from unittest.mock import patch

from digital_twin_sensor.collectors.browser_tab import sanitize_browser_url
from digital_twin_sensor.collectors.macos_active_window import build_event


class BrowserTabCaptureTests(unittest.TestCase):
    def test_sanitizes_browser_url_by_default(self):
        detail, findings = sanitize_browser_url(
            "https://example.com/private/path?token=abc#secret",
            {
                "mask_pii": True,
                "redact_url_paths": True,
                "browser_tab_store_url_path": False,
                "browser_tab_store_query": False,
            },
        )

        self.assertEqual(detail["url_domain"], "example.com")
        self.assertNotIn("private/path", detail["url"])
        self.assertNotIn("token=abc", detail["url"])
        self.assertNotIn("secret", detail["url"])
        self.assertEqual(detail["url_path_policy"], "redacted")
        self.assertGreaterEqual(findings["url"], 1)

    def test_safari_tab_metadata_updates_event_artifact(self):
        config = {
            "subject_id": "local-user",
            "context_capture_depth": 2,
            "capture_window_title": True,
            "redact_sensitive_titles": True,
            "mask_pii": True,
            "mask_configured_names": True,
            "mask_ip_addresses": True,
            "redact_url_paths": True,
            "name_terms_to_mask": ["Gagan"],
            "ignored_apps": [],
            "enable_browser_tab_details": True,
            "browser_tab_detail_min_depth": 2,
            "browser_tab_detail_apps": ["Safari"],
            "browser_tab_store_url_path": False,
            "browser_tab_store_query": False,
            "sensitive_title_keywords": [],
            "domain_rules": [
                {
                    "domain": "browser-research",
                    "apps": ["Safari"],
                    "keywords": ["arxiv", "docs"],
                }
            ],
        }

        with patch(
            "digital_twin_sensor.collectors.macos_active_window.active_window",
            return_value=("Safari", "Safari"),
        ), patch(
            "digital_twin_sensor.collectors.macos_active_window.active_browser_tab_detail",
            return_value={
                "kind": "browser_tab",
                "status": "captured",
                "source": "safari_applescript",
                "app": "Safari",
                "title": "[name] reading Task Model Induction",
                "url": "https://arxiv.org/[redacted-path]",
                "url_domain": "arxiv.org",
                "url_scheme": "https",
                "url_path_policy": "redacted",
                "url_query_policy": "redacted",
                "redaction_findings": {"name": 1, "url": 1},
                "privacy": "tab title redacted; URL path/query/fragment redacted by default",
            },
        ):
            event = build_event(config, 15.0)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["app"], "Safari")
        self.assertEqual(event["domain"], "browser-research")
        self.assertIn("[name]", event["artifact"])
        surface_detail = event["metadata"]["surface_detail"]
        self.assertEqual(surface_detail["url_domain"], "arxiv.org")
        self.assertNotIn("Task Model", surface_detail["url"])
        self.assertEqual(event["metadata"]["redaction_findings"]["name"], 1)
        self.assertEqual(event["metadata"]["redaction_findings"]["url"], 1)


if __name__ == "__main__":
    unittest.main()
