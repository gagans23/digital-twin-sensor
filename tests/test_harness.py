import unittest
from datetime import timedelta

from digital_twin_sensor.config import DEFAULT_CONFIG
from digital_twin_sensor.context_pack import build_context_pack
from digital_twin_sensor.harness import load_scenarios, run_harness, run_scenario
from digital_twin_sensor.store import filter_window, utc_now
from digital_twin_sensor.working_spheres import build_working_spheres


def aged_event(event_id, *, days_ago, artifact="quarter end close checklist"):
    start = utc_now() - timedelta(days=days_ago)
    return {
        "id": event_id,
        "subject_id": "test",
        "source": "test",
        "app": "Numbers",
        "title": artifact,
        "artifact": artifact,
        "domain": "data",
        "action": "focus",
        "ts_start": start.isoformat(),
        "ts_end": (start + timedelta(seconds=120)).isoformat(),
        "dwell_seconds": 120.0,
        "metadata": {"redaction_findings": {}},
    }


class WindowEnforcementTests(unittest.TestCase):
    """Regression: `days` used to be metadata only. Builders stamped a window on
    their output without enforcing it, so a caller passing a wider event list got
    stale evidence labelled as fresh. Found by the harness, not by a unit test."""

    def test_filter_window_drops_events_outside_the_window(self):
        events = [aged_event(1, days_ago=30), aged_event(2, days_ago=1)]
        self.assertEqual(len(filter_window(events, 3)), 1)

    def test_working_spheres_enforce_their_own_window(self):
        events = [aged_event(i, days_ago=30) for i in range(1, 6)]
        result = build_working_spheres(events, dict(DEFAULT_CONFIG), days=3)
        self.assertNotEqual(result["status"], "ready")

    def test_context_pack_does_not_export_stale_evidence(self):
        events = [aged_event(i, days_ago=30) for i in range(1, 6)]
        pack = build_context_pack(events, dict(DEFAULT_CONFIG), days=3, target="kiro")
        self.assertNotEqual(pack["status"], "ready")


class HarnessTests(unittest.TestCase):
    def test_golden_set_loads_and_passes(self):
        report = run_harness()
        self.assertEqual(report["leak_count"], 0, msg=f"leaks: {report['failed']}")
        self.assertTrue(report["ok"], msg=f"failed scenarios: {report['failed']}")

    def test_every_scenario_is_named_and_described(self):
        for scenario in load_scenarios():
            self.assertTrue(scenario.get("name"))
            self.assertTrue(scenario.get("description"))

    def test_leak_canary_would_actually_fail_if_a_canary_escaped(self):
        """Guard the guard: a canary that is present in the trace must be detected."""
        scenario = {
            "name": "self_check",
            "description": "deliberately impossible expectation",
            "apply_collection_redaction": False,
            "must_not_surface": ["payments gateway retry"],
            "events": [{"title": "payments gateway retry logic", "repeat": 5}],
        }
        result = run_scenario(scenario)
        self.assertTrue(result.leaks)
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
