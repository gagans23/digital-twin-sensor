"""Tests for secure aggregation.

The claim this layer makes is structural: the aggregator cannot read any
individual contribution, and the totals are still exactly right. Both halves
need holding, and so does the refusal — a partial cohort must fail loudly
rather than return a plausible wrong number.
"""

from __future__ import annotations

import secrets
import unittest

from digital_twin_sensor.aggregation import (
    CohortError,
    DEFAULT_CLIP,
    MODULUS,
    VocabularyError,
    ThemeVocabulary,
    build_contribution,
    cohort_digest,
    load_vocabulary,
    mask_contribution,
    secure_sum,
    wilson_interval,
)
from digital_twin_sensor.synthesis import synthesize_secure, theme_of_sphere

SECRET = b"cohort-secret-for-tests-only"
ROUND = "2026-W35"


def sphere(domain: str, task: str = "", **extra):
    return {"domain": domain, "task": task, "label": task, "gate_mode": "allowed", **extra}


def activities(*spheres):
    return {"spheres": list(spheres)}


class VocabularyTests(unittest.TestCase):
    def test_shipped_vocabulary_loads(self):
        vocabulary = load_vocabulary()
        self.assertGreater(len(vocabulary), 0)
        self.assertTrue(all(vocabulary.descriptions[t] for t in vocabulary.themes))

    def test_every_theme_needs_a_description(self):
        import json, tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "v.json"
            path.write_text(json.dumps({"version": "1", "themes": [{"id": "a"}]}))
            with self.assertRaises(VocabularyError):
                load_vocabulary(path)

    def test_reordering_changes_the_digest(self):
        first = ThemeVocabulary(("a", "b"), {"a": "x", "b": "y"}, "1")
        second = ThemeVocabulary(("b", "a"), {"a": "x", "b": "y"}, "1")
        self.assertNotEqual(first.digest, second.digest)


class ContributionTests(unittest.TestCase):
    def setUp(self):
        self.vocabulary = load_vocabulary()

    def test_undeclared_work_cannot_be_counted(self):
        vector = build_contribution(
            activities(sphere("astrology", "star charts")), self.vocabulary, theme_of=theme_of_sphere
        )
        self.assertEqual(sum(vector), 0)

    def test_contribution_is_clipped(self):
        many = activities(*[sphere("coding", "implement feature") for _ in range(50)])
        vector = build_contribution(many, self.vocabulary, theme_of=theme_of_sphere)
        self.assertEqual(max(vector), DEFAULT_CLIP)

    def test_restricted_spheres_are_excluded(self):
        vector = build_contribution(
            activities(sphere("coding", "implement", sensitivity="high")),
            self.vocabulary,
            theme_of=theme_of_sphere,
        )
        self.assertEqual(sum(vector), 0)


class MaskingTests(unittest.TestCase):
    def setUp(self):
        self.vocabulary = load_vocabulary()
        self.cohort = [f"subj_{index:02d}" for index in range(6)]

    def _contribute(self, subject: str, vector: list[int]):
        return mask_contribution(
            vector,
            subject_key=subject,
            cohort=self.cohort,
            round_id=ROUND,
            cohort_secret=SECRET,
        )

    def test_masks_cancel_and_totals_are_exact(self):
        truth = [
            [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            [1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0],
            [1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0],
            [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            [0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0],
        ]
        contributions = [self._contribute(s, v) for s, v in zip(self.cohort, truth)]
        totals = secure_sum(contributions)
        expected = [sum(row[i] for row in truth) for i in range(len(truth[0]))]
        self.assertEqual(totals, expected)

    def test_a_single_masked_contribution_reveals_nothing(self):
        """The whole point: one vector on its own must not look like its input."""
        plain = [1] + [0] * (len(self.vocabulary) - 1)
        masked = self._contribute(self.cohort[0], plain)["masked_vector"]
        self.assertNotEqual(masked, plain)
        # A one-hot input must not leave the rest of the vector at zero.
        self.assertGreater(sum(1 for value in masked if value != 0), len(plain) - 1)
        # And the masked values must be spread across the ring, not near zero.
        self.assertGreater(max(masked), MODULUS // 4)

    def test_partial_cohort_refuses_rather_than_guessing(self):
        contributions = [self._contribute(s, [0] * len(self.vocabulary)) for s in self.cohort[:-1]]
        with self.assertRaises(CohortError) as caught:
            secure_sum(contributions)
        self.assertIn("incomplete", str(caught.exception))

    def test_wrong_secret_is_detected_not_silently_wrong(self):
        good = [self._contribute(s, [0] * len(self.vocabulary)) for s in self.cohort[:-1]]
        bad = mask_contribution(
            [0] * len(self.vocabulary),
            subject_key=self.cohort[-1],
            cohort=self.cohort,
            round_id=ROUND,
            cohort_secret=b"a-different-secret",
        )
        with self.assertRaises(CohortError):
            secure_sum(good + [bad])

    def test_masks_are_round_bound(self):
        first = self._contribute(self.cohort[0], [0] * len(self.vocabulary))
        second = mask_contribution(
            [0] * len(self.vocabulary),
            subject_key=self.cohort[0],
            cohort=self.cohort,
            round_id="2026-W36",
            cohort_secret=SECRET,
        )
        self.assertNotEqual(first["masked_vector"], second["masked_vector"])

    def test_mixed_rounds_are_refused(self):
        contributions = [self._contribute(s, [0] * len(self.vocabulary)) for s in self.cohort]
        contributions[0]["round_id"] = "2026-W36"
        with self.assertRaises(CohortError):
            secure_sum(contributions)

    def test_a_subject_must_belong_to_its_cohort(self):
        with self.assertRaises(CohortError):
            mask_contribution(
                [0] * len(self.vocabulary),
                subject_key="subj_stranger",
                cohort=self.cohort,
                round_id=ROUND,
                cohort_secret=SECRET,
            )

    def test_cohort_digest_is_order_independent(self):
        self.assertEqual(cohort_digest(["b", "a"]), cohort_digest(["a", "b"]))


class SecureSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.vocabulary = load_vocabulary()
        self.totals = [7, 2, 6, 0, 0, 5, 1, 0, 8, 3, 0, 0]

    def test_floor_is_enforced_on_totals(self):
        result = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        self.assertTrue(all(theme["subjects"] >= 5 for theme in result["themes"]))

    def test_cohort_below_the_floor_is_refused(self):
        with self.assertRaises(ValueError):
            synthesize_secure(self.totals, self.vocabulary, cohort_size=3, min_subjects=5)

    def test_confidence_is_an_interval_not_a_score(self):
        result = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        for theme in result["themes"]:
            low, high = theme["confidence_interval"]
            self.assertLessEqual(low, theme["share_of_cohort"])
            self.assertGreaterEqual(high, theme["share_of_cohort"])

    def test_smaller_cohort_widens_the_interval(self):
        """Uncertainty must fall out of the numbers, not a chosen weight."""
        small = synthesize_secure([5] * len(self.vocabulary), self.vocabulary, cohort_size=5, min_subjects=5)
        large = synthesize_secure([50] * len(self.vocabulary), self.vocabulary, cohort_size=50, min_subjects=5)
        small_width = small["themes"][0]["confidence_interval"][1] - small["themes"][0]["confidence_interval"][0]
        large_width = large["themes"][0]["confidence_interval"][1] - large["themes"][0]["confidence_interval"][0]
        self.assertGreater(small_width, large_width)

    def test_withheld_count_is_banded_not_exact(self):
        result = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        self.assertIn(result["themes_withheld_band"], {"none", "1-2", "3-5", "6+"})
        self.assertNotIn("themes_withheld", result)

    def test_no_per_subject_field_survives_into_the_output(self):
        result = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        blob = repr(result)
        for banned in ("subject_key", "subj_", "masked_vector", "spheres"):
            self.assertNotIn(banned, blob)

    def test_vocabulary_is_pinned_in_the_output(self):
        result = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        self.assertEqual(result["vocabulary_digest"], self.vocabulary.digest)

    def test_noise_is_off_by_default_and_declared_when_on(self):
        plain = synthesize_secure(self.totals, self.vocabulary, cohort_size=9, min_subjects=5)
        self.assertIsNone(plain["epsilon"])
        noisy = synthesize_secure(self.totals, self.vocabulary, cohort_size=40, min_subjects=5, epsilon=1.0)
        self.assertEqual(noisy["epsilon"], 1.0)
        decisions = {d["field"]: d["decision"] for d in noisy["decisions"]}
        self.assertEqual(decisions["differential_privacy"], "allow")


class EndToEndTests(unittest.TestCase):
    def test_six_sensors_to_a_published_theme_without_a_readable_contribution(self):
        vocabulary = load_vocabulary()
        cohort = [f"subj_{i}" for i in range(6)]
        secret = secrets.token_bytes(32)

        traces = {
            "subj_0": activities(sphere("coding", "implement router"), sphere("communication", "email")),
            "subj_1": activities(sphere("coding", "implement parser"), sphere("communication", "email")),
            "subj_2": activities(sphere("coding", "review the diff"), sphere("communication", "email")),
            "subj_3": activities(sphere("coding", "implement gate"), sphere("communication", "email")),
            "subj_4": activities(sphere("coding", "implement store"), sphere("operations", "incident page")),
            "subj_5": activities(sphere("coding", "implement cli"), sphere("communication", "email")),
        }

        contributions = []
        for subject, trace in traces.items():
            vector = build_contribution(trace, vocabulary, theme_of=theme_of_sphere)
            contributions.append(
                mask_contribution(
                    vector, subject_key=subject, cohort=cohort, round_id=ROUND, cohort_secret=secret
                )
            )

        # Nothing readable crosses the wire.
        for item in contributions:
            self.assertNotIn("subject_key", item)
            self.assertGreater(max(item["masked_vector"]), MODULUS // 4)

        totals = secure_sum(contributions)
        result = synthesize_secure(totals, vocabulary, cohort_size=len(cohort), min_subjects=5)

        published = {theme["theme"] for theme in result["themes"]}
        self.assertIn("coding:implementation", published)   # 5 of 6 subjects
        self.assertNotIn("coding:review", published)        # 1 subject, below the floor
        self.assertNotIn("operations:incident", published)  # 1 subject, below the floor


if __name__ == "__main__":
    unittest.main()
