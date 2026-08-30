import unittest

from digital_twin_sensor.synthesis import (
    subject_key,
    synthesize_collective,
)


def sphere(label, domain="coding", events=10, dwell=3600.0, age=600):
    return {
        "label": label,
        "domain": domain,
        "events": events,
        "dwell_seconds": dwell,
        "last_age_seconds": age,
    }


def bundle(name, spheres):
    return {"subject_key": subject_key(name), "activities": {"spheres": spheres}}


class SynthesisTests(unittest.TestCase):
    def test_theme_below_floor_is_withheld_not_emitted(self):
        bundles = [bundle(f"d{i}", [sphere("personal tax return filing", "finance")]) for i in range(3)]
        result = synthesize_collective(bundles, min_subjects=5)
        self.assertEqual(result["themes_emitted"], 0)
        self.assertEqual(result["themes_withheld"], 1)
        self.assertEqual(result["status"], "below_floor")

    def test_theme_clearing_the_floor_is_emitted(self):
        bundles = [bundle(f"d{i}", [sphere("payments gateway retry logic")]) for i in range(6)]
        result = synthesize_collective(bundles, min_subjects=5)
        self.assertEqual(result["themes_emitted"], 1)
        self.assertGreaterEqual(result["themes"][0]["subjects"], 5)

    def test_one_busy_subject_cannot_clear_the_floor_alone(self):
        """Volume from a single person must never substitute for corroboration."""
        bundles = [bundle("solo", [sphere("payments gateway retry logic", events=5000, dwell=999999.0)])]
        result = synthesize_collective(bundles, min_subjects=5)
        self.assertEqual(result["themes_emitted"], 0)

    def test_subject_keys_are_never_emitted(self):
        bundles = [bundle(f"d{i}", [sphere("payments gateway retry logic")]) for i in range(6)]
        result = synthesize_collective(bundles, min_subjects=5)
        blob = repr(result)
        for item in bundles:
            self.assertNotIn(item["subject_key"], blob)

    def test_subject_key_is_stable_and_not_reversible(self):
        self.assertEqual(subject_key("device-a"), subject_key("device-a"))
        self.assertNotEqual(subject_key("device-a"), subject_key("device-b"))
        self.assertNotIn("device-a", subject_key("device-a"))

    def test_a_floor_of_one_is_rejected(self):
        with self.assertRaises(ValueError):
            synthesize_collective([], min_subjects=1)


if __name__ == "__main__":
    unittest.main()
