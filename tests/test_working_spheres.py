import json
import unittest

from digital_twin_sensor.working_spheres import build_working_spheres

from datetime import timedelta

from digital_twin_sensor.store import utc_now

# Fixtures are anchored to "now" rather than a fixed calendar date. The builders
# enforce their own rolling window, so a hardcoded date silently ages out of it.
_BASE = utc_now() - timedelta(hours=2)


def ts(offset_seconds: int) -> str:
    return (_BASE + timedelta(seconds=offset_seconds)).isoformat()


def event(
    event_id,
    *,
    app,
    artifact,
    domain,
    start,
    end,
    dwell=15.0,
    findings=None,
    action="focus",
):
    return {
        "id": event_id,
        "subject_id": "Gagan Sachdeva",
        "source": "macos_active_window",
        "app": app,
        "title": artifact,
        "artifact": artifact,
        "domain": domain,
        "action": action,
        "ts_start": start,
        "ts_end": end,
        "dwell_seconds": dwell,
        "metadata": {"redaction_findings": findings or {}},
    }


class WorkingSphereTests(unittest.TestCase):
    def test_reconnects_interrupted_work_into_one_sphere(self):
        events = [
            event(
                1,
                app="Google Chrome",
                artifact="Task Model Induction arxiv paper",
                domain="browser-research",
                start=ts(0),
                end=ts(15),
            ),
            event(
                2,
                app="Mail",
                artifact="Inbox update",
                domain="communication",
                start=ts(15),
                end=ts(30),
            ),
            event(
                3,
                app="Google Chrome",
                artifact="Task Model Induction arxiv paper",
                domain="browser-research",
                start=ts(30),
                end=ts(45),
            ),
        ]

        result = build_working_spheres(events, {"context_capture_depth": 1}, days=1)

        self.assertEqual(result["status"], "ready")
        self.assertGreaterEqual(result["stats"]["sphere_count"], 2)
        research = [
            sphere
            for sphere in result["spheres"]
            if sphere["domain"] == "browser-research"
        ][0]
        self.assertEqual(research["events"], 2)
        self.assertGreaterEqual(research["return_count"], 1)
        self.assertIn("resume_pack", research)

    def test_excludes_system_events_and_does_not_emit_subject_id(self):
        events = [
            event(
                1,
                app="loginwindow",
                artifact="system state",
                domain="system",
                action="system",
                start=ts(0),
                end=ts(15),
            ),
            event(
                2,
                app="Google Chrome",
                artifact="[name] checkout [credit-card]",
                domain="browser-research",
                start=ts(15),
                end=ts(30),
                findings={"name": 1, "credit_card": 1},
            ),
        ]

        result = build_working_spheres(events, {"context_capture_depth": 1}, days=1)

        self.assertEqual(result["stats"]["excluded_system_events"], 1)
        self.assertEqual(result["spheres"][0]["gate_mode"], "masked")
        payload = json.dumps(result)
        self.assertNotIn("Gagan", payload)
        self.assertNotIn("Sachdeva", payload)
        self.assertNotIn("4111", payload)
        self.assertIn("[credit-card]", payload)


if __name__ == "__main__":
    unittest.main()
