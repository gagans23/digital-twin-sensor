import json
import unittest

from digital_twin_sensor.working_spheres import build_working_spheres


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
                start="2026-08-28T08:00:00+00:00",
                end="2026-08-28T08:00:15+00:00",
            ),
            event(
                2,
                app="Mail",
                artifact="Inbox update",
                domain="communication",
                start="2026-08-28T08:00:15+00:00",
                end="2026-08-28T08:00:30+00:00",
            ),
            event(
                3,
                app="Google Chrome",
                artifact="Task Model Induction arxiv paper",
                domain="browser-research",
                start="2026-08-28T08:00:30+00:00",
                end="2026-08-28T08:00:45+00:00",
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
                start="2026-08-28T08:00:00+00:00",
                end="2026-08-28T08:00:15+00:00",
            ),
            event(
                2,
                app="Google Chrome",
                artifact="[name] checkout [credit-card]",
                domain="browser-research",
                start="2026-08-28T08:00:15+00:00",
                end="2026-08-28T08:00:30+00:00",
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
