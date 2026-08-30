import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from digital_twin_sensor.config import DEFAULT_CONFIG
from digital_twin_sensor.context_pack import build_context_pack
from digital_twin_sensor.learning import LearningStore, build_learning_state
from digital_twin_sensor.store import utc_now


def event(
    event_id,
    *,
    app="Kiro",
    artifact="Digital twin learning mode implementation",
    domain="coding",
    dwell=40.0,
):
    now = utc_now()
    start = now - timedelta(minutes=30) + timedelta(seconds=event_id * 45)
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
        "metadata": {"redaction_findings": {}},
    }


def config():
    value = dict(DEFAULT_CONFIG)
    value.update(
        {
            "subject_id": "local-user",
            "context_capture_depth": 2,
            "mask_pii": True,
            "mask_configured_names": True,
            "name_terms_to_mask": ["Gagan", "Sachdeva"],
            "fleet_allowed_export_targets": ["kiro", "gitlab"],
        }
    )
    return value


class LearningModeTests(unittest.TestCase):
    def test_builds_context_cards_and_persists_feedback(self):
        events = [
            event(1),
            event(2, artifact="Digital twin learning mode implementation"),
            event(3, app="Safari", artifact="Context engineering research notes", domain="browser-research"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.sqlite"
            cfg = config()

            state = build_learning_state(events, cfg, subject_id=cfg["subject_id"], db_path=db_path, days=1)
            self.assertEqual(state["policy"], "learning-mode-v1-local")
            self.assertGreaterEqual(state["stats"]["context_cards"], 1)
            self.assertTrue(all(card["id"].startswith("card_") for card in state["cards"]))

            pack = build_context_pack(events, cfg, days=1, target="kiro")
            sphere_id = state["cards"][0]["sphere_id"]
            store = LearningStore(db_path)
            try:
                saved = store.add_feedback(
                    subject_id=cfg["subject_id"],
                    pack_id=pack["pack_id"],
                    sphere_id=sphere_id,
                    label="useful",
                    note="Gagan saw account 4111 1111 1111 1111 in the handoff",
                    config=cfg,
                )
            finally:
                store.close()

            self.assertEqual(saved["label"], "useful")
            self.assertNotIn("Gagan", saved["note"])
            self.assertNotIn("4111 1111 1111 1111", saved["note"])
            self.assertIn("[name]", saved["note"])
            self.assertIn("[credit-card]", saved["note"])

            learned = build_learning_state(events, cfg, subject_id=cfg["subject_id"], db_path=db_path, days=1)
            self.assertEqual(learned["stats"]["feedback_count"], 1)
            self.assertEqual(learned["stats"]["useful_count"], 1)
            self.assertGreaterEqual(learned["stats"]["validated_cards"], 1)

    def test_rejects_invalid_feedback_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config()
            store = LearningStore(Path(tmp) / "learning.sqlite")
            try:
                with self.assertRaises(ValueError):
                    store.add_feedback(
                        subject_id=cfg["subject_id"],
                        pack_id="pack_test",
                        scope="evidence",
                        label="useful",
                        config=cfg,
                    )
                with self.assertRaises(ValueError):
                    store.add_feedback(
                        subject_id=cfg["subject_id"],
                        pack_id="pack_test",
                        label="not_a_label",
                        config=cfg,
                    )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
