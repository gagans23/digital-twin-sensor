import json
import unittest

from digital_twin_sensor.context_graph import build_context_graph

from datetime import timedelta

from digital_twin_sensor.store import utc_now

# Fixtures are anchored to "now" rather than a fixed calendar date. The builders
# enforce their own rolling window, so a hardcoded date silently ages out of it.
_BASE = utc_now() - timedelta(hours=2)


def ts(offset_seconds: int) -> str:
    return (_BASE + timedelta(seconds=offset_seconds)).isoformat()


class ContextGraphTests(unittest.TestCase):
    def test_builds_privacy_gated_graph(self):
        events = [
            {
                "id": 1,
                "subject_id": "Gagan Sachdeva",
                "source": "macos_active_window",
                "app": "Google Chrome",
                "title": "X-SYNTH paper - arxiv",
                "artifact": "X-SYNTH paper - arxiv",
                "domain": "browser-research",
                "action": "focus",
                "ts_start": ts(0),
                "ts_end": ts(15),
                "dwell_seconds": 15.0,
                "metadata": {"redaction_findings": {}},
            },
            {
                "id": 2,
                "subject_id": "Gagan Sachdeva",
                "source": "macos_active_window",
                "app": "Google Chrome",
                "title": "[name] checkout [credit-card]",
                "artifact": "[name] checkout [credit-card]",
                "domain": "browser-research",
                "action": "focus",
                "ts_start": ts(15),
                "ts_end": ts(30),
                "dwell_seconds": 15.0,
                "metadata": {"redaction_findings": {"name": 1, "credit_card": 1}},
            },
        ]

        graph = build_context_graph(events, {"context_capture_depth": 1}, days=1)

        self.assertEqual(graph["status"], "ready")
        self.assertGreater(graph["stats"]["node_count"], 0)
        self.assertGreater(graph["stats"]["edge_count"], 0)
        self.assertGreaterEqual(graph["stats"]["gates"]["masked"], 1)
        self.assertIn("Pre-Storage Redaction", {gate["name"] for gate in graph["privacy_gates"]})

        payload = json.dumps(graph)
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("Sachdeva", payload)
        self.assertNotIn("4111", payload)
        self.assertIn("blocked card data", payload)
        self.assertIn("masked identity/contact", payload)


if __name__ == "__main__":
    unittest.main()
