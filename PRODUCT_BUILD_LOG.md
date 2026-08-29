# Product Build Log

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

## Current Live Product Posture

Implemented:

- local background collector
- local dashboard
- watchdog self-heal check
- product doctor CLI
- product health API
- Product Ops UI
- pause/resume controls
- retention purge controls
- context graph
- working spheres
- context packs
- Depth 2 browser metadata
- Depth 3 allowlisted Accessibility metadata
- PII masking before storage
- raw-upload boundary

Still product gaps:

- encrypted SQLite storage
- menubar status/pause control
- GitLab summary sync
- OCR summary gate for opaque apps
- feedback-labeled evaluation loop
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
3. Add feedback buttons on context packs and evidence results.
4. Add a context-card maintenance job that consolidates working spheres nightly.
5. Add local OCR summaries only for explicitly allowlisted opaque apps.
6. Add GitLab summary sync for approved context packs and health reports.
7. Add paper metrics: task-resume time, context precision, leakage rate, freshness, and failure attribution.
