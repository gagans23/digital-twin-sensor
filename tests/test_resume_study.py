"""Tests for the resume-time measurement.

The measurement this project has promised publicly, so its arithmetic and its
refusals both need holding still. In particular: it must decline to compare
conditions on a sample too small to mean anything, because a tool that reports
a confident delta from six data points is worse than one that reports nothing.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from digital_twin_sensor.resume_study import (
    MIN_EVENTS_PER_CONDITION,
    assign_condition,
    describe,
    find_resume_events,
    format_resume_study_markdown,
    run_resume_study,
)

BASE = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def event(offset_minutes: float, artifact: str, dwell: float = 300.0, app: str = "Kiro") -> dict:
    start = BASE + timedelta(minutes=offset_minutes)
    return {
        "app": app,
        "artifact": artifact,
        "title": artifact,
        "domain": "coding",
        "ts_start": start.isoformat(),
        "ts_end": (start + timedelta(seconds=dwell)).isoformat(),
        "dwell_seconds": dwell,
    }


class DistributionTests(unittest.TestCase):
    def test_empty_distribution_is_not_a_zero(self):
        dist = describe([])
        self.assertEqual(dist.n, 0)
        self.assertIsNone(dist.median)

    def test_percentiles_use_nearest_rank(self):
        dist = describe([10.0, 20.0, 30.0, 40.0, 1000.0])
        self.assertEqual(dist.median, 30.0)
        self.assertEqual(dist.maximum, 1000.0)
        # The tail must survive into the report; a mean would bury it.
        self.assertEqual(dist.p90, 1000.0)


class ConditionAssignmentTests(unittest.TestCase):
    def test_assignment_is_deterministic_for_a_date(self):
        moment = datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc)
        self.assertEqual(assign_condition(moment), assign_condition(moment))

    def test_consecutive_days_alternate(self):
        first = assign_condition(datetime(2026, 8, 20, tzinfo=timezone.utc))
        second = assign_condition(datetime(2026, 8, 21, tzinfo=timezone.utc))
        self.assertNotEqual(first, second)

    def test_time_of_day_does_not_change_the_block(self):
        morning = assign_condition(datetime(2026, 8, 20, 6, tzinfo=timezone.utc))
        evening = assign_condition(datetime(2026, 8, 20, 23, tzinfo=timezone.utc))
        self.assertEqual(morning, evening)


class ResumeDetectionTests(unittest.TestCase):
    def test_detects_a_return_after_a_gap(self):
        events = [
            event(0, "payments-service/router.py"),
            event(60, "slack"),                          # 55 min gap: interruption
            event(70, "payments-service/router.py"),      # substantive return
        ]
        resumes = find_resume_events(events)
        self.assertEqual(len(resumes), 1)
        # Interruption ends when the next activity starts; the return is 10 min later.
        self.assertAlmostEqual(resumes[0].resume_seconds, 600.0, delta=1)

    def test_continuous_work_produces_no_resume_events(self):
        events = [event(i * 6, "payments-service/router.py") for i in range(6)]
        self.assertEqual(find_resume_events(events), [])

    def test_a_glance_is_not_a_resume(self):
        events = [
            event(0, "payments-service/router.py"),
            event(60, "slack"),
            event(70, "payments-service/router.py", dwell=5.0),   # glance
            event(90, "payments-service/router.py", dwell=400.0), # real return
        ]
        resumes = find_resume_events(events)
        self.assertEqual(len(resumes), 1)
        self.assertAlmostEqual(resumes[0].resume_seconds, 1800.0, delta=1)

    def test_never_returning_produces_no_resume_event(self):
        events = [
            event(0, "payments-service/router.py"),
            event(60, "slack"),
            event(120, "email"),
        ]
        self.assertEqual(find_resume_events(events), [])

    def test_short_pause_is_thinking_not_interruption(self):
        events = [
            event(0, "payments-service/router.py"),
            event(12, "payments-service/router.py"),
        ]
        self.assertEqual(find_resume_events(events), [])


class StudyReportTests(unittest.TestCase):
    def _trace(self, days: int) -> list[dict]:
        events = []
        for day in range(days):
            base = day * 24 * 60
            for block in range(4):
                offset = base + block * 180
                events.append(event(offset, f"service/module_{day}.py"))
                events.append(event(offset + 60, "slack", artifact_app := "Slack"))
                events.append(event(offset + 75, f"service/module_{day}.py"))
        return events

    def test_refuses_to_compare_on_a_thin_sample(self):
        report = run_resume_study(
            [
                event(0, "a.py"),
                event(60, "slack"),
                event(70, "a.py"),
            ],
            days=3650,
        )
        self.assertFalse(report["comparable"])
        self.assertIsNone(report["comparison"])
        self.assertIn("no treatment comparison is valid", " ".join(report["caveats"]))

    def test_reports_distributions_even_when_it_will_not_compare(self):
        report = run_resume_study(
            [event(0, "a.py"), event(60, "slack"), event(70, "a.py")], days=3650
        )
        self.assertEqual(report["resume_events"], 1)
        self.assertIsNotNone(report["overall"]["median_seconds"])

    def test_caveats_always_name_the_blinding_confound(self):
        report = run_resume_study([], days=14)
        self.assertTrue(any("blinded" in c for c in report["caveats"]))

    def test_markdown_renders_with_no_data(self):
        rendered = format_resume_study_markdown(run_resume_study([], days=14))
        self.assertIn("Task-resume study", rendered)
        self.assertIn("No comparison reported", rendered)

    def test_large_trace_without_exposure_never_produces_comparison(self):
        events = []
        for day in range(24):  # 24 days, alternating blocks
            for block in range(3):
                offset = day * 24 * 60 + block * 300
                events.append(event(offset, f"m{day}.py"))
                events.append(event(offset + 60, "slack"))
                events.append(event(offset + 75, f"m{day}.py"))
        report = run_resume_study(events, days=3650)
        self.assertGreaterEqual(report["conditions"]["exposure_unknown"]["n"], MIN_EVENTS_PER_CONDITION)
        self.assertFalse(report["comparable"])
        self.assertFalse(report["exposure_verified"])
        self.assertIsNone(report["comparison"])


if __name__ == "__main__":
    unittest.main()


class SampledCollectorTests(unittest.TestCase):
    """Regression for the failure the first real run exposed.

    The collector samples every ~15 seconds. Judging "substantive" on a single
    event's dwell meant no event ever qualified, no anchor was ever found, and
    the study reported zero resumes across a trace of 11,783 events — silently,
    which was the worse half of the bug.
    """

    def _sampled(self, offset_minutes: float, artifact: str, count: int, interval: float = 15.0):
        events = []
        for index in range(count):
            start = BASE + timedelta(minutes=offset_minutes, seconds=index * interval)
            events.append(
                {
                    "app": "Kiro",
                    "artifact": artifact,
                    "title": artifact,
                    "domain": "coding",
                    "ts_start": start.isoformat(),
                    "ts_end": (start + timedelta(seconds=interval)).isoformat(),
                    "dwell_seconds": interval,
                }
            )
        return events

    def test_short_samples_accumulate_into_substantive_work(self):
        events = (
            self._sampled(0, "service/router.py", 20)      # 5 minutes of work
            + self._sampled(60, "slack", 8)                # interruption, then Slack
            + self._sampled(75, "service/router.py", 20)   # returns to the work
        )
        resumes = find_resume_events(events)
        self.assertEqual(len(resumes), 1, "sampled events must accumulate into a run")
        self.assertAlmostEqual(resumes[0].resume_seconds, 900.0, delta=30)

    def test_zero_result_explains_itself(self):
        # Everything below the substantive threshold: the detector must say why.
        report = run_resume_study(self._sampled(0, "a.py", 2), days=3650, substantive_seconds=600)
        self.assertEqual(report["resume_events"], 0)
        self.assertIsNotNone(report["no_resumes_because"])
        self.assertIn("substantive", report["no_resumes_because"])
        self.assertIn("runs", report["diagnostics"])

    def test_continuous_trace_reports_no_gap_rather_than_nothing(self):
        report = run_resume_study(self._sampled(0, "a.py", 40), days=3650)
        self.assertEqual(report["resume_events"], 0)
        self.assertIn("gap", report["no_resumes_because"])

    def test_markdown_surfaces_the_explanation(self):
        rendered = format_resume_study_markdown(
            run_resume_study(self._sampled(0, "a.py", 40), days=3650)
        )
        self.assertIn("No resume events.", rendered)
        self.assertIn("Detector trace:", rendered)
