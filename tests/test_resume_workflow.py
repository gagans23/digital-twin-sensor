import io
import json
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
import unittest

from digital_twin_sensor.cli import cmd_encrypt_store
from digital_twin_sensor.config import load_config
from digital_twin_sensor.learning import LearningStore
from digital_twin_sensor.resume import ResumeConflict, build_resume_view, resume_action
from digital_twin_sensor.store import EventStore, utc_now
from tests.test_hardening import SyntheticFixture, event, CRYPTO


class ResumeWorkflowTests(SyntheticFixture):
    def setUp(self):
        super().setUp()
        store = EventStore(self.db)
        store.insert_event(event())
        store.insert_event(event(2))
        store.close()
        self.view = build_resume_view(self.db, self.cfg)
        self.sphere = self.view["selected_sphere_id"]

    def save(self, **values):
        payload = dict(action="checkpoint", sphere_id=self.sphere, base_checkpoint_id=None,
                       state="Synthetic gateway tests passed", next_step="Review retry handling", question="Is cancellation covered?")
        payload.update(values)
        return resume_action(self.db, self.cfg, payload)

    def start(self, request_id=None):
        return resume_action(self.db, self.cfg, dict(action="start", sphere_id=self.sphere, request_id=request_id or str(uuid4())))

    def test_observation_does_not_become_confirmed_progress(self):
        self.assertEqual(self.view["status"], "ready")
        self.assertIsNone(self.view["checkpoint"])
        self.assertTrue(self.view["observations"])
        self.assertIn("not a confirmed", self.view["inference"]["basis"])
        self.assertFalse(self.view["change"]["content_changes_verified"])
        self.assertEqual(self.view["sessions"], [])

    def test_checkpoints_persist_with_revision_history(self):
        first = self.save()
        self.save(base_checkpoint_id=first["checkpoint_id"], state="Correction: one retry test still fails")
        view = build_resume_view(self.db, self.cfg, sphere_id=self.sphere)
        self.assertEqual(len(view["history"]), 2)
        self.assertTrue(view["checkpoint"]["state"].startswith("Correction:"))
        self.assertEqual(view["checkpoint"]["source"], "user_report")
        self.assertEqual(view["change"]["recent_samples_since"], 0)

    def test_concurrent_edit_cannot_silently_overwrite_checkpoint(self):
        self.save()
        with self.assertRaises(ResumeConflict):
            self.save(state="Stale browser draft")

    def test_sensitive_notes_masked_even_if_collection_masking_disabled(self):
        self.cfg["mask_pii"] = False
        self.save(state="Contact fixture.person@example.com")
        view = build_resume_view(self.db, self.cfg)
        self.assertNotIn("fixture.person@example.com", json.dumps(view))
        self.assertNotIn(b"fixture.person@example.com", self.db.read_bytes())

    def test_current_masking_policy_applies_to_old_checkpoint(self):
        self.save(state="Ask SyntheticName for review")
        self.cfg["name_terms_to_mask"] = ["SyntheticName"]
        view = build_resume_view(self.db, self.cfg)
        self.assertNotIn("SyntheticName", json.dumps(view["checkpoint"]))

    def test_privacy_restriction_hides_notes_and_prevents_resume(self):
        self.save()
        store = LearningStore(self.db)
        store.add_feedback(subject_id=self.cfg["subject_id"], pack_id=self.view["pack_id"],
                           sphere_id=self.sphere, label="too_private", config=self.cfg)
        store.close()
        view = build_resume_view(self.db, self.cfg, sphere_id=self.sphere)
        self.assertEqual(view["status"], "blocked")
        self.assertEqual(build_resume_view(self.db, self.cfg)["status"], "blocked")
        self.assertIsNone(view["checkpoint"])
        self.assertEqual(view["observations"], [])
        self.assertNotIn("gateway", json.dumps(view).lower())
        with self.assertRaises(ResumeConflict):
            self.start()

    def test_wrong_task_does_not_receive_another_tasks_checkpoint(self):
        self.save()
        other = build_resume_view(self.db, self.cfg, sphere_id="unknown-task")
        self.assertEqual(other["status"], "empty")
        self.assertIsNone(other["checkpoint"])

    def test_pause_and_missing_samples_do_not_imply_no_work(self):
        self.cfg["collection_paused"] = True
        self.assertEqual(build_resume_view(self.db, self.cfg)["coverage"]["state"], "paused")
        store = EventStore(self.db)
        store.delete_all()
        store.close()
        self.cfg["collection_paused"] = False
        view = build_resume_view(self.db, self.cfg)
        self.assertEqual(view["coverage"]["state"], "unavailable")
        self.assertIn("does not mean", view["coverage"]["detail"])

    def test_session_request_is_idempotent_and_exposure_is_not_assumed(self):
        request_id = str(uuid4())
        session = self.start(request_id)
        self.start(request_id)
        view = build_resume_view(self.db, self.cfg)
        self.assertEqual(len(view["sessions"]), 1)
        self.assertIsNone(view["sessions"][0]["shown_at"])
        self.assertIsNone(view["sessions"][0]["outcome"])
        with self.assertRaises(ResumeConflict):
            resume_action(self.db, self.cfg, dict(action="outcome", session_id=session["session_id"], outcome="progress"))

    def test_display_and_self_report_are_separate_and_outcome_is_immutable(self):
        session = self.start()["session_id"]
        resume_action(self.db, self.cfg, dict(action="shown", session_id=session))
        payload = dict(action="outcome", session_id=session, outcome="progress")
        resume_action(self.db, self.cfg, payload)
        resume_action(self.db, self.cfg, payload)
        row = build_resume_view(self.db, self.cfg)["sessions"][0]
        self.assertIsNotNone(row["shown_at"])
        self.assertEqual(row["outcome"], "progress")
        with self.assertRaises(ResumeConflict):
            resume_action(self.db, self.cfg, {**payload, "outcome": "no_progress"})

    def test_subject_cannot_update_another_subjects_session(self):
        session = self.start()["session_id"]
        with self.assertRaises(ResumeConflict):
            resume_action(self.db, {**self.cfg, "subject_id": "another-subject"}, dict(action="shown", session_id=session))

    def test_invalid_input_does_not_create_records(self):
        for values in ({"state": ""}, {"state": "x" * 1201}, {"question": []}, {"days": -1}):
            with self.assertRaises(ValueError):
                self.save(**values)
        self.assertIsNone(build_resume_view(self.db, self.cfg)["checkpoint"])

    def test_purge_removes_resume_data_even_if_events_already_deleted(self):
        self.save()
        self.start()
        store = EventStore(self.db)
        store.conn.execute("DELETE FROM events")
        store.conn.commit()
        store.delete_all(subject_id=self.cfg["subject_id"])
        for table in ("resume_checkpoints", "resume_sessions"):
            self.assertEqual(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        store.close()

    def test_retention_invalidates_resume_snapshots(self):
        self.save()
        self.start()
        store = EventStore(self.db)
        store.delete_before(subject_id=self.cfg["subject_id"], cutoff=utc_now())
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM resume_checkpoints").fetchone()[0], 0)
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM resume_sessions").fetchone()[0], 0)
        store.close()

    @unittest.skipUnless(CRYPTO, "encryption extra not installed")
    def test_existing_and_new_checkpoint_text_is_encrypted(self):
        self.save(state="Distinctive synthetic checkpoint phrase")
        with patch("digital_twin_sensor.crypto._load_from_keyring", return_value=None), \
             patch("digital_twin_sensor.crypto._store_in_keyring", return_value=False), redirect_stdout(io.StringIO()):
            cmd_encrypt_store(Namespace(config=self.config_path, db=self.db, status=False))
        self.cfg = load_config(self.config_path)
        view = build_resume_view(self.db, self.cfg)
        self.save(base_checkpoint_id=view["checkpoint"]["id"], state="New encrypted checkpoint phrase")
        self.assertNotIn(b"Distinctive synthetic checkpoint phrase", self.db.read_bytes())
        self.assertNotIn(b"New encrypted checkpoint phrase", self.db.read_bytes())
        self.assertEqual(build_resume_view(self.db, self.cfg)["checkpoint"]["state"], "New encrypted checkpoint phrase")
