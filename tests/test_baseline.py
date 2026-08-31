"""Tests for the drift gate itself.

A regression detector nobody has tried to break is a regression detector that
reports green forever. Each test here weakens one thing deliberately and asserts
the comparison notices.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from digital_twin_sensor.baseline import compare, load_baseline, summarise, write_baseline
from digital_twin_sensor.harness import run_harness


def _report(**overrides):
    base = {
        "mean_recall": 1.0,
        "mean_noise_ratio": 0.0,
        "leak_count": 0,
        "results": [
            {
                "name": "coding_resume",
                "recall": 1.0,
                "noise_ratio": 0.0,
                "leaks": [],
                "pack_chars": 10000,
                "gate_counts": {"allow": 6, "summarize": 7, "deny": 9},
            }
        ],
    }
    base.update(overrides)
    return base


class BaselineComparisonTests(unittest.TestCase):
    def setUp(self):
        self.baseline = summarise(_report())

    def test_identical_run_is_not_a_regression(self):
        self.assertTrue(compare(_report(), self.baseline)["ok"])

    def test_recall_drop_beyond_tolerance_fails(self):
        report = _report(mean_recall=0.90)
        report["results"][0]["recall"] = 0.90
        result = compare(report, self.baseline)
        self.assertFalse(result["ok"])
        self.assertTrue(any("recall" in item for item in result["regressions"]))

    def test_small_fluctuation_is_tolerated(self):
        report = _report(mean_recall=0.995)
        report["results"][0]["recall"] = 0.995
        self.assertTrue(compare(report, self.baseline)["ok"])

    def test_new_leak_fails_even_with_perfect_recall(self):
        report = _report(leak_count=1)
        report["results"][0]["leaks"] = ["4111111111111111"]
        self.assertFalse(compare(report, self.baseline)["ok"])

    def test_gate_that_stops_denying_fails_even_when_recall_improves(self):
        """The case a pass/fail gate cannot see: better recall, weaker refusal."""
        report = _report()
        report["results"][0]["gate_counts"] = {"allow": 8, "summarize": 7, "deny": 6}
        result = compare(report, self.baseline)
        self.assertFalse(result["ok"])
        self.assertTrue(any("denials" in item for item in result["regressions"]))

    def test_pack_growth_beyond_tolerance_fails(self):
        report = _report()
        report["results"][0]["pack_chars"] = 20000
        self.assertFalse(compare(report, self.baseline)["ok"])

    def test_disappearing_scenario_fails(self):
        report = _report()
        report["results"] = []
        self.assertFalse(compare(report, self.baseline)["ok"])

    def test_improvement_passes_and_is_reported(self):
        better = summarise(_report(mean_recall=0.8))
        better["scenarios"]["coding_resume"]["recall"] = 0.8
        result = compare(_report(), better)
        self.assertTrue(result["ok"])
        self.assertTrue(result["improvements"])

    def test_baseline_roundtrips_and_excludes_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            write_baseline(_report(generated_at="2026-08-31T00:00:00+00:00"), path)
            loaded = load_baseline(path)
            self.assertNotIn("generated_at", json.dumps(loaded))
            self.assertTrue(compare(_report(), loaded)["ok"])


class CommittedBaselineTests(unittest.TestCase):
    def test_repository_baseline_matches_the_current_harness(self):
        """The committed baseline must describe this commit, or the gate is
        comparing against fiction."""
        path = Path(__file__).resolve().parents[1] / "harness" / "baseline.json"
        self.assertTrue(path.exists(), "harness/baseline.json is missing")
        result = compare(run_harness(), load_baseline(path))
        self.assertTrue(result["ok"], msg=f"baseline is stale: {result['regressions']}")


if __name__ == "__main__":
    unittest.main()
