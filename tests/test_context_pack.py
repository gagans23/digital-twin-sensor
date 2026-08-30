import json
import unittest
from datetime import timedelta

from digital_twin_sensor.context_pack import build_context_pack
from digital_twin_sensor.store import utc_now


def event(
    event_id,
    *,
    app="Kiro",
    artifact="Digital twin context pack implementation",
    domain="coding",
    dwell=15.0,
    findings=None,
):
    now = utc_now()
    start = now - timedelta(seconds=event_id * 20)
    end = start + timedelta(seconds=dwell)
    return {
        "id": event_id,
        "subject_id": "Gagan Sachdeva",
        "source": "macos_active_window",
        "app": app,
        "title": artifact,
        "artifact": artifact,
        "domain": domain,
        "action": "focus",
        "ts_start": start.isoformat(),
        "ts_end": end.isoformat(),
        "dwell_seconds": dwell,
        "metadata": {"redaction_findings": findings or {}},
    }


class ContextPackTests(unittest.TestCase):
    def test_builds_summary_only_pack_with_markdown_export(self):
        pack = build_context_pack(
            [
                event(2, app="Safari", artifact="X-SYNTH paper context notes", domain="browser-research"),
                event(1, app="Kiro", artifact="Digital twin context pack implementation", domain="coding"),
            ],
            {
                "context_capture_depth": 2,
                "fleet_allowed_export_targets": ["kiro", "gitlab"],
                "mask_pii": True,
                "mask_configured_names": True,
                "browser_tab_store_url_path": False,
                "browser_tab_store_query": False,
            },
            days=1,
            target="kiro",
        )

        self.assertEqual(pack["status"], "ready")
        self.assertTrue(pack["pack_id"].startswith("pack_"))
        self.assertFalse(pack["privacy"]["raw_events_included"])
        self.assertFalse(pack["privacy"]["subject_id_included"])
        self.assertIn("Privacy Gate", pack["export"]["markdown"])
        self.assertIn("Pack ID", pack["export"]["markdown"])
        self.assertGreater(pack["admission"]["counts"]["deny"], 0)
        self.assertTrue(all("id" not in item for item in pack["context"]["recent_path"]))
        self.assertTrue(
            all(item["evidence_key"].startswith("ev_") for item in pack["context"]["top_artifacts"])
        )
        self.assertTrue(
            all(item["evidence_key"].startswith("path_") for item in pack["context"]["recent_path"])
        )
        payload = json.dumps(pack)
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("Sachdeva", payload)

    def test_blocks_remote_target_not_allowed_by_policy(self):
        pack = build_context_pack(
            [event(1)],
            {
                "context_capture_depth": 1,
                "fleet_allowed_export_targets": ["kiro"],
                "mask_pii": True,
            },
            days=1,
            target="gitlab",
        )

        self.assertEqual(pack["status"], "blocked")
        self.assertFalse(pack["target"]["allowed"])
        self.assertIn("not allowed", pack["admission"]["target_reason"])
        self.assertIn("Context Pack: Blocked", pack["export"]["markdown"])

    def test_marks_redacted_sphere_as_masked_without_raw_sensitive_values(self):
        pack = build_context_pack(
            [
                event(
                    1,
                    app="Safari",
                    artifact="[name] checkout [credit-card]",
                    domain="browser-research",
                    findings={"name": 1, "credit_card": 1},
                )
            ],
            {
                "context_capture_depth": 1,
                "fleet_allowed_export_targets": ["kiro"],
                "mask_pii": True,
            },
            days=1,
            target="kiro",
        )

        self.assertEqual(pack["status"], "ready")
        self.assertEqual(pack["context"]["working_sphere"]["gate_mode"], "masked")
        self.assertGreater(pack["admission"]["counts"]["mask"], 0)
        payload = json.dumps(pack)
        self.assertIn("[credit-card]", payload)
        self.assertNotIn("4111111111111111", payload)

    def test_re_redacts_export_labels_as_defense_in_depth(self):
        pack = build_context_pack(
            [
                event(
                    1,
                    app="Safari",
                    artifact="Gagan checkout 4111 1111 1111 1111",
                    domain="browser-research",
                )
            ],
            {
                "context_capture_depth": 1,
                "fleet_allowed_export_targets": ["kiro"],
                "mask_pii": True,
                "mask_configured_names": True,
                "name_terms_to_mask": ["Gagan"],
            },
            days=1,
            target="kiro",
        )

        payload = json.dumps(pack)
        self.assertEqual(pack["context"]["working_sphere"]["gate_mode"], "masked")
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("4111 1111 1111 1111", payload)
        self.assertIn("[name]", payload)
        self.assertIn("[credit-card]", payload)


if __name__ == "__main__":
    unittest.main()
