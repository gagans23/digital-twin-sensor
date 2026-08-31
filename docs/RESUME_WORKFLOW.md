# Resume My Work

Implemented 31 August 2026. Open the local dashboard at `http://127.0.0.1:8765/#resume` after reloading the installed UI.

## What It Does

Choose an inferred working sphere. The page separates three kinds of information:

- **Your report:** the latest state, next step, and unresolved question you explicitly saved. Saving another checkpoint appends a revision; it does not erase the previous one.
- **Observed:** the admitted recent foreground samples. After a checkpoint, the page counts which of the displayed samples are newer than the checkpoint's last observed activity. This is a limited sample comparison, not a source-file diff or proof of progress.
- **Inferred:** the existing task-category next-step template, labelled as a guess. There is no new model, semantic task planner, or training loop.

The coverage banner distinguishes recent, stale, paused, and unavailable samples. Permission status remains unverified; absence of samples is not absence of work.

Start resume records an explicit request. The browser acknowledges display only after rendering the returned view while the document is visible. A later outcome is a separate user report: progress, no progress, or context not used. These events do not prove reading, eye attention, independent progress, or causal benefit. Merely opening or refreshing the page creates no session and assigns no treatment.

## Architecture

```text
Redacted event store -> working spheres -> existing memory admission gate
                                          |
                                          v
                                  local resume summary
                                  /        |         \
                          observations  inference  user checkpoint
                                          |
                                explicit Start resume
                                          |
                           display acknowledgement -> reported outcome
```

`digital_twin_sensor/resume.py` builds this local view through `build_context_pack` with `self_review` and `local_file`. Unresolved restrictions and high-sensitivity blocks therefore apply before checkpoint text or evidence is returned. Restricted picker entries have generic labels. Checkpoint notes are local only and are not automatically added to existing agent exports.

The existing `LearningStore` owns two additional SQLite tables:

| Table | Stored information |
| --- | --- |
| `resume_checkpoints` | Subject/sphere link, timestamp, and redacted JSON containing user state, next step, question, observed-through timestamp, and `source=user_report` |
| `resume_sessions` | Request UUID, subject/sphere link, pack ID, checkpoint ID, request/display/completion timestamps, and optional outcome |

Checkpoint JSON follows optional field encryption and is included in encryption migration. Session identifiers and timestamps are not encrypted. Current redaction settings are reapplied when checkpoint text is read.

Full purge deletes both tables' subject records. Retention currently invalidates all subject resume records when any source events are removed, matching the conservative cache policy. This can remove recent manual checkpoints too; preserving them safely needs per-field source lineage and a separate user-note retention policy. Checkpoints older than the configured retention window are not displayed.

Write operations serialize evidence reads and writes with SQLite `BEGIN IMMEDIATE`. Checkpoint saves carry `base_checkpoint_id`, so two open windows cannot silently overwrite each other's revision. Drafts survive in-page refresh; task/window switching is disabled while a draft is being edited. A page reload does not persist an unsaved draft.

## API

Both routes require the existing local `X-DTS-Token` header and Host/Origin checks.

- `GET /api/resume?days=14&sphere_id=...`: task choices, coverage, gated evidence, checkpoint/history, inference, and the ten most recent sessions for the selected task.
- `POST /api/resume`: JSON action, described below. Subject identity comes from local configuration, never the request body.

| Action | Required fields | Result |
| --- | --- | --- |
| `checkpoint` | `sphere_id`, `state`, `base_checkpoint_id` (null initially); optional `next_step`, `question`, `days` | Redacted revision ID |
| `start` | `sphere_id`, client-generated UUID `request_id`; optional `days` | Session ID and server-built resume view |
| `shown` | `session_id` | Idempotent display acknowledgement |
| `outcome` | `session_id`, `outcome` in `progress`, `no_progress`, `not_used` | Timestamped self-report |

Text fields are limited to 1,200 characters before redaction. Invalid input returns 400. Stale revisions, missing sessions, changed retry context, blocked tasks, or conflicting completed outcomes return 409. Session retries with the same request ID are idempotent while the pack/checkpoint identity remains unchanged. A completed outcome cannot silently be overwritten. The acknowledgement is client-reported, not independently verified exposure.

## Verification And Next Work

Synthetic tests cover revision history, conflicting saves, privacy blocks, current-policy redaction, subject isolation, invalid input, purge/retention, encrypted old/new notes, request idempotency, and separate display/outcome records. UI regressions cover draft preservation, blocked-state clearing, and HTML escaping.

Release checks: 169 Python tests, seven JavaScript tests, and five baseline harness scenarios. The wheel is also checked from outside the source checkout.

Browser checks exercised save, start, display acknowledgement, no-progress reporting, refresh during a draft, discard, and reload persistence. Layout was checked at 1440 x 1000 and 390 x 844 with no control overflow. Tests used a disposable synthetic store, not user traces.

Next: durable task membership with explicit split/merge correction; longer evidence histories with source lineage; a validated progress endpoint; prospective assignment and comparison groups. The historical resume study remains descriptive. These session records are a useful starting point for instrumentation, not a completed experiment or evidence that the graph helps.
