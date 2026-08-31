# Product Build Log

## 2026-08-31: Resume My Work

1. Added a local resume view using existing sphere inference and memory admission checks, without expanding collection.
2. Separated sampled foreground evidence, task-category guesses, and explicitly saved user checkpoints.
3. Added redacted checkpoint revisions, optimistic conflict detection, encryption migration, and purge/retention cleanup.
4. Added explicit resume requests, client display acknowledgements, and separate self-reported outcomes; no treatment assignment or benefit claim.
5. Added UI draft preservation, restricted-state clearing, and responsive form/evidence layouts.
6. Verified the main flow against a disposable synthetic store in desktop/mobile browser views. Technical details and remaining limitations are in `docs/RESUME_WORKFLOW.md`.

## 2026-08-31: Hardening After Critical Review

1. Reproduced privacy, lifecycle, packaging, grouping, and study failures using synthetic fixtures at `53f4e94`.
2. Connected encryption to runtime paths; fixed migration; encrypted learning text and made missing keys fail closed.
3. Restricted dashboard hosts, origins, API sessions, and static assets; kept remote binding disabled.
4. Enforced title-source permissions, full deletion of derived memory, and feedback restrictions at export.
5. Removed suppressed topic disclosure, required artifact evidence for grouping, and stabilized repeated artifact seeds.
6. Removed unsupported treatment comparisons from the resume report and added sustained task-detour detection.
7. Added 18 integrated regression tests, bringing the Python suite to 152, plus four dependency-free JavaScript regressions. Existing harness cases pass without baseline drift. Browser testing found and fixed a duplicate connector renderer that interrupted dashboard refresh.
8. Replaced the stale Claude handover and added root `CLAUDE.md`; documented reasons, runtime contracts, and the next task-resume milestone.

Packaging, UI, and live verification are recorded in `docs/HARDENING_2026_08_31.md`.

The initial evidence-backed resumption workflow was subsequently added above. Durable task membership, source lineage, and outcome validation remain open. No productivity effect or complete enterprise readiness is claimed.

Build date: 2026-08-29

This log records the step-by-step product hardening pass that moved the prototype from a local research demo toward an always-on personal context product.

## Objective

Turn the digital twin sensor into a product loop:

```text
Collect -> Redact -> Graph -> Working Spheres -> Context Packs -> Product Doctor -> Research Backlog
```

The product must stay useful without becoming silent surveillance. The design target is a living context graph with privacy gates, not a raw profile vector and not "collect everything."

## Build Steps

1. Audited the running sensor and dashboard services.
   - Verified the collector LaunchAgent is installed and running.
   - Verified the dashboard LaunchAgent is installed and running at `http://127.0.0.1:8765/`.
   - Verified samples are flowing into the local SQLite store.

2. Added an always-on watchdog layer.
   - Added `digital_twin_sensor/health.py`.
   - Added `digital-twin-sensor doctor`.
   - Added `digital-twin-sensor watchdog --fix`.
   - Added a macOS LaunchAgent template for `com.local.digital-twin-watchdog`.
   - Added install/uninstall scripts for the watchdog LaunchAgent.

3. Added product health APIs.
   - Added `/api/health` for service, freshness, permission, privacy, and paper-gap diagnostics.
   - Added `/api/admin/watchdog` so the dashboard can trigger a local self-heal check.

4. Added Product Ops UI.
   - Added a Product Ops tab to the dashboard.
   - Shows collector, dashboard, and watchdog availability.
   - Shows sample freshness, macOS Accessibility posture, automation permission posture, PII masking, URL minimization, raw upload boundary, and database presence.
   - Shows what is implemented beyond the X-SYNTH paper.
   - Shows known deviations from the paper.
   - Shows product gaps that should be closed before enterprise deployment.

5. Added research-to-product backlog.
   - Added last-three-year paper ideas directly into the health report and Product Ops tab.
   - Each item is framed as a reasonable product build, research experiment, or future architecture step.
   - Each item links to the source paper.

6. Added tests for product health.
   - Covered health report construction with mocked service state and active-window permission.
   - Covered watchdog self-heal behavior for stale collection.

7. Added user control and retention primitives.
   - Added `collection_paused` to config.
   - The long-running collector reloads config each loop, so pause/resume takes effect without reinstalling services.
   - Added `digital-twin-sensor pause` and `digital-twin-sensor resume`.
   - Added guarded purge commands for all events or rows older than a retention threshold.
   - Added dashboard pause/resume and purge-expired controls in the Privacy tab.

8. Added Learning Mode v1.
   - Added stable `pack_id` values to context packs.
   - Added opaque `evidence_key` values for top artifacts and recent-path evidence.
   - Added `context_feedback` for local useful/wrong/stale/too-broad/too-private/missing-context labels.
   - Added `context_cards` that consolidate working spheres into maintainable memory cards.
   - Added `/api/learning` and `/api/feedback`.
   - Added `digital-twin-sensor learning` and `digital-twin-sensor feedback`.
   - Added dashboard feedback buttons and a Learning Mode tab.
   - Kept learned router updates offline-only until labelled evaluation data exists.

9. Added scheduled learning maintenance.
   - Added `digital-twin-sensor maintain-learning`.
   - Added `com.local.digital-twin-learning` LaunchAgent template.
   - Added install/uninstall scripts for the learning maintenance job.
   - Added Product Doctor visibility for learning maintenance posture.
   - Documented four-service local deployment.

10. Added Depth 4 local OCR summary gate.
   - Added a macOS Apple Vision OCR helper using `VNRecognizeTextRequest`.
   - Added Tesseract CLI fallback support inside the same temporary-window-image helper.
   - Added `digital_twin_sensor.collectors.local_ocr`.
   - Added app allowlist, confidence, line-limit, and timeout policy keys.
   - Wired OCR behind Depth 4 after browser and Accessibility metadata.
   - Stored only redacted OCR text hints, summary, provider, confidence, and redaction findings.
   - Updated Signal Depth, Privacy, and Product Doctor payloads for OCR posture.

## Current Live Product Posture

Implemented:

- local background collector
- local dashboard
- watchdog self-heal check
- scheduled learning maintenance
- product doctor CLI
- product health API
- Product Ops UI
- pause/resume controls
- retention purge controls
- Learning Mode feedback labels
- evolving context cards
- context graph
- working spheres
- context packs
- Depth 2 browser metadata
- Depth 3 allowlisted Accessibility metadata
- Depth 4 local OCR summaries for allowlisted opaque apps
- PII masking before storage
- raw-upload boundary

Still product gaps:

- encrypted SQLite storage
- menubar status/pause control
- GitLab summary sync
- learned query x digital-twin-signature router

## Validation Results

Validated on 2026-08-29:

- `python3 -m unittest discover -s tests`: 22 tests passed
- `python3 -m compileall digital_twin_sensor`: passed
- `node --check digital_twin_sensor/ui_static/app.js`: passed
- `git diff --check`: passed
- `/api/health`: collector ready, dashboard ready, watchdog installed, no blocked checks
- `/api/overview`: collection unpaused, retention set to 30 days, no expired rows
- live collector LaunchAgent: running
- live dashboard LaunchAgent: running
- watchdog LaunchAgent: scheduled every 60 seconds with last exit code 0
- pause/resume API: verified; collect-once refuses storage while paused and resumes cleanly
- Product Ops desktop visual QA: no document overflow; research backlog renders 8 cards
- Privacy mobile visual QA: no document overflow; collection controls visible and responsive

Validated on 2026-08-31:

- `python -m unittest discover -s tests`: 68 tests passed in a venv with the encrypted extra
- `python -m compileall digital_twin_sensor`: passed
- `node --check digital_twin_sensor/ui_static/app.js`: passed
- `git diff --check`: passed
- `swiftc helpers/macos-ocr-probe.swift`: passed
- OCR helper smoke: frontmost-app mismatch returns a structured skipped payload

Known non-blocking attention item:

- macOS may ask for Automation permission the first time Safari, Google Chrome, or Ibo Pro Player app-specific metadata is inspected.

## Publishable Paper Direction

Working title:

```text
Privacy-Gated Context Synthesis from Digital Attention Traces
```

Core claim to test:

```text
Device-native attention traces can improve agent handoff and task resumption when transformed into privacy-gated context graphs and summary-only context packs.
```

Do not claim yet:

- that the prototype is a faithful human twin
- that attention causes outcomes
- that the current router matches the learned X-SYNTH router
- that camera gaze or full-content capture is necessary

Claims supported by the implementation:

- foreground attention can be captured continuously on macOS with visible local diagnostics
- redaction can happen before persistence
- raw rows are not required for useful Kiro/Codex/GitLab context packs
- a graph/sphere abstraction is more explainable than an opaque vector profile
- product UI should expose freshness, permission, privacy, and known research gaps

## Experiment Log Template

Use this format for paper-grade evaluation:

```text
date:
task:
target agent:
context condition: none | query-only | raw top-k | gated context pack | graph + sphere pack
task outcome:
time to resume:
useful evidence count:
irrelevant evidence count:
privacy gate counts:
human rating:
failure attribution: modality | retrieval | synthesis | stale memory | privacy gate | UI
notes:
```

## Next Sprint

1. Add encrypted storage.
2. Add menubar status/pause indicator.
3. Add GitLab summary sync for approved context packs and health reports.
4. Add offline replay for learned Query x Digital Twin Signature router policies.
5. Add paper metrics: task-resume time, context precision, leakage rate, freshness, and failure attribution.
6. Add conflict resolution and forgetting policies for context cards.
7. Add app-specific structured connectors to replace OCR where APIs are available.
## 2026-08-31: Optional Opik Observability

Added in an isolated worktree to avoid sharing Claude's staging area. The build
adds a local operational log, trace spans at collection/admission/learning/resume
boundaries, an observability dashboard, and an explicit Opik exporter.

Decisions:

1. Keep the Python 3.9 sensor dependency-free. Opik 2.2.45 needs Python 3.10+, so
   export runs in a separate worker environment.
2. Reconstruct an allowlisted schema at persistence and export. Never reuse raw
   application logging or automatically capture function inputs/outputs.
3. Use synchronous SDK REST calls to distinguish failed delivery from successful
   enqueueing. Disable SDK analytics, Sentry, redirects, and ambient proxies.
4. Bound retention, record count, child spans, batch size, and retries. Preserve
   operation behavior when logging fails. Expose pending/failed/expired records.
5. Treat changing consent as a new generation. Old local history and pending
   batches must not become a backlog for a newly approved destination.
6. Expose timing as sensitive operational data, not anonymized data or a measure
   of human attention. No paper-quality outcome claim follows from these traces.

Validation includes the actual pinned SDK against a synthetic localhost HTTP
receiver, canaries for input/error leakage, queue/consent/purge tests, and existing
runtime/UI regressions. Real server persistence still requires a synthetic smoke
against the user's approved Opik deployment. No cloud destination is configured
by this build. See `docs/OPIK_OBSERVABILITY.md` for setup and remaining limits.
