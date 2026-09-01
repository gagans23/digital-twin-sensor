# Resume My Work

Implemented 31 August 2026. Open the local dashboard at `http://127.0.0.1:8765/#resume` after reloading the installed UI.

## What It Does

Choose an inferred working sphere. The page separates three kinds of information:

- **Your report:** the latest state, next step, and unresolved question you explicitly saved. Saving another checkpoint appends a revision; it does not erase the previous one.
- **Observed:** the admitted recent foreground samples. After a checkpoint, the page counts which of the displayed samples are newer than the checkpoint's last observed activity. This is a limited sample comparison, not a source-file diff or proof of progress.
- **Inferred:** the existing task-category next-step template, labelled as a guess. There is no new model, semantic task planner, or training loop.

The coverage banner distinguishes recent, stale, paused, and unavailable samples. Permission status remains unverified; absence of samples is not absence of work.

An inferred sphere is not treated as a durable human task automatically. You can
save a recognizable task name, explicitly link another inferred activity group,
or split a mistaken link. The system never merges saved tasks on its own. Names
are redacted before storage and current masking is reapplied on read.

Start resume records an explicit request. The browser acknowledges display only after rendering the returned view while the document is visible. A later outcome is a separate user report: progress, no progress, or context not used. These events do not prove reading, eye attention, independent progress, or causal benefit. Merely opening or refreshing the page creates no session and assigns no treatment.

## Architecture

```text
Redacted event store -> inferred working spheres -> user-confirmed task bindings
                                                     |
                                            memory admission gate
                                                     |
                                           scoped resume summary
                                           /       |        \
                                   observations inference checkpoint
                                                     |
                                           explicit Start resume
                                                     |
                                  display acknowledgement -> reported outcome
```

`digital_twin_sensor/resume.py` builds this local view through `build_context_pack` with `self_review` and `local_file`. Unresolved restrictions and high-sensitivity blocks therefore apply before checkpoint text or evidence is returned. Restricted picker entries have generic labels. Checkpoint notes are local only and are not automatically added to existing agent exports.

The existing `LearningStore` owns five additional SQLite tables:

| Table | Stored information |
| --- | --- |
| `resume_checkpoints` | Subject/sphere link, timestamp, and redacted JSON containing user state, next step, question, observed-through timestamp, and `source=user_report` |
| `resume_sessions` | Request UUID, subject/sphere link, pack ID, checkpoint ID, request/display/completion timestamps, and optional outcome |
| `task_identities` | Random task ID, subject, encrypted-or-redacted user-confirmed name, revision, and creation time |
| `task_bindings` | Explicit sphere-to-task aliases with source activity `last_seen`; at most 32 groups per task |
| `task_identity_edits` | Fixed create/rename/link/unlink audit operation, task/sphere IDs, and timestamp; no task name |

Checkpoint JSON follows optional field encryption and is included in encryption migration. Session identifiers and timestamps are not encrypted. Current redaction settings are reapplied when checkpoint text is read.

Full purge deletes all five tables' subject records. Retention invalidates resume
records when source events are removed and expires bindings using the linked
activity group's actual `last_seen`, not dashboard access. Orphan identities and
old edit records are removed. This conservative policy can remove recent manual
checkpoints too; preserving them safely still needs per-field source lineage and
a separate user-note retention policy.

Write operations serialize evidence reads and writes with SQLite `BEGIN IMMEDIATE`.
Checkpoint saves carry `base_checkpoint_id`; all task-dependent writes carry
`identity_revision`; links also carry the destination revision. Two open windows
therefore cannot silently overwrite a checkpoint or task membership. Checkpoints
and sessions record the exact set of aliases used to build them. After a split,
a record built from a wider scope is withheld from both sides instead of leaking
notes across the correction. Drafts survive in-page refresh; navigation is
disabled while a checkpoint or task-name draft is being edited.

## API

Both routes require the existing local `X-DTS-Token` header and Host/Origin checks.

- `GET /api/resume?days=14&sphere_id=...`: task choices, coverage, gated evidence, checkpoint/history, inference, and the ten most recent sessions for the selected task.
- `POST /api/resume`: JSON action, described below. Subject identity comes from local configuration, never the request body.

| Action | Required fields | Result |
| --- | --- | --- |
| `checkpoint` | `sphere_id`, `state`, `base_checkpoint_id`, `identity_revision` (either may be null initially); optional `next_step`, `question`, `days` | Redacted revision ID |
| `start` | `sphere_id`, client-generated UUID `request_id`, `identity_revision`; optional `days` | Session ID and server-built resume view |
| `shown` | `session_id` | Idempotent display acknowledgement |
| `outcome` | `session_id`, `outcome` in `progress`, `no_progress`, `not_used` | Timestamped self-report |
| `save_task` | `sphere_id`, redacted `name`, `identity_revision` | New identity or versioned rename |
| `link_task` | Unbound `sphere_id`, `task_id`, null `identity_revision`, `target_revision` | Explicit versioned alias link |
| `unlink_task` | Bound `sphere_id`, `identity_revision` | Explicit split; wider-scope records become inadmissible |

Text fields are limited to 1,200 characters before redaction. Invalid input returns 400. Stale revisions, missing sessions, changed retry context, blocked tasks, or conflicting completed outcomes return 409. Session retries with the same request ID are idempotent while the pack/checkpoint identity remains unchanged. A completed outcome cannot silently be overwritten. The acknowledgement is client-reported, not independently verified exposure.

## Verification And Next Work

Synthetic tests cover revision history, conflicting saves and stale identity edits,
privacy propagation, current-policy redaction, explicit link/split correction,
wider-scope invalidation, subject isolation, purge/retention, encryption, request
idempotency, and separate display/outcome records. UI regressions cover both
draft types, explicit unlink confirmation, revision tokens, blocked-state
clearing, and HTML escaping.

Release checks: 169 Python tests, seven JavaScript tests, and five baseline harness scenarios. The wheel is also checked from outside the source checkout.

Browser checks exercised save, start, display acknowledgement, no-progress reporting, refresh during a draft, discard, and reload persistence. Layout was checked at 1440 x 1000 and 390 x 844 with no control overflow. Tests used a disposable synthetic store, not user traces.

Next: per-field source lineage; a validated progress endpoint; prospective
assignment and comparison groups; and task-level usefulness measures that do not
confuse self-report with independent outcome. The historical resume study remains
descriptive. These records are useful instrumentation, not evidence that the
graph improves work.
