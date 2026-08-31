# Changelog

## Unreleased

### August 31 Hardening

- Fixed dashboard traversal and added session/Host/Origin checks; remote binding is refused.
- Connected encryption to runtime event and learning paths and repaired migration.
- Enforced title-source permissions, derived-memory purge, feedback export restrictions, and explicit resolution.
- Removed suppressed topic disclosure and corrected broad sphere merging and repeated-artifact identity.
- Included connector manifests in wheels and added installed-package verification.
- Historical resume analysis is now descriptive only: calendar parity is not observed treatment exposure. This supersedes the alternating-condition claim below.
- Added 17 integrated regression tests and refreshed the Claude handover.

### Added

- architecture decision records (`docs/adr/`) — ten decisions with what drove
  them, the test that enforces each, and what evidence would reverse it
- threat model (`docs/THREAT_MODEL.md`) — assets, six adversaries and what each
  actually gets, including what the encryption boundary deliberately leaves
  readable
- validation plan (`docs/VALIDATION.md`) — every asserted-but-unmeasured claim
  with acceptance criteria, so the debts are collectable rather than merely
  disclosed
- property-based leak tests (`tests/test_fuzz_leak_gate.py`) — generated hostile
  inputs against the redaction and export boundaries, seeded and dependency-free
- harness baseline gate (`digital_twin_sensor/baseline.py`,
  `harness/baseline.json`) — fails on drift against the last accepted scores,
  including a gate that stops denying while recall improves
- `harness --baseline` and `harness --update-baseline`
- optional `fuzz` extra for deeper local property testing
- **task-resume measurement** (`digital_twin_sensor/resume_study.py`,
  `resume-study` command, ADR 0011) — derives interruption and resume events
  from the existing trace with no new collection and no self-reporting, assigns
  conditions in alternating day blocks fixed by the date, reports distributions
  rather than means, and refuses to print a comparison until both conditions
  clear a minimum count. This is the instrument for `docs/VALIDATION.md` V2, the
  one benefit the project promises and has never measured.

### Fixed

- **the resume study could never detect anything on a real trace.** "Substantive"
  was judged on a single sampled event's dwell, but the collector samples every
  few seconds, so no event ever qualified, no prior task was ever identified, and
  the first real run reported zero resumes across 11,783 events. Dwell now
  accumulates across consecutive attention on the same cluster, and a zero result
  names the stage that produced it instead of printing an empty table.

### Fixed

- **card numbers could be hidden by a neighbouring digit.** The greedy candidate
  pattern swallowed an adjacent digit — `Invoice 3 4111 1111 1111 1111` — failed
  Luhn as a combined span, and returned the whole card unmasked. The pattern now
  requires plausible card chunks (3-6 digit groups, or one unbroken 13-19 digit
  run), which also correctly handles Amex 4-6-5 grouping.
- **secret detection was character-class-narrow.** Token patterns did not accept
  mixed `-`/`_` separators, so credential-shaped strings carrying both survived
  redaction. Classes widened; over-masking is the safe direction of failure.
- **the harness reported an empty admission gate for every scenario.**
  `_gate_counts` read `pack["decisions"]`, but decisions live under
  `pack["admission"]["decisions"]`. The gate-count metric had never measured
  anything.
- **`python -m digital_twin_sensor` discarded its exit code**, so a leak exited
  0 when invoked that way. The console-script wrapper had been masking this in
  CI.

All four were found by the new property tests and baseline work, not by the
golden set.

## 0.1.0

Initial local-first product prototype.

### Added

- macOS active-window attention collector
- native window probe fallback support
- local SQLite event store
- pre-storage PII and secret redaction
- Digital Twin Signature profile
- X-SYNTH-lite attention filters
- living context graph
- working spheres and resume packs
- Memory Admission Gate
- Kiro/Codex/GitLab context-pack export
- local dashboard
- Workfabric-inspired digital twin cockpit
- Signal Depth tab
- Fleet Manager Lite
- Product Ops tab
- product doctor CLI and health API
- watchdog LaunchAgent
- pause/resume collection
- retention purge controls
- research synthesis and paper build log
- Learning Mode with local pack, sphere, and evidence feedback
- stable context pack IDs and opaque evidence keys
- evolving context cards for working-sphere maintenance
- `/api/learning`, `/api/feedback`, `learning`, and `feedback` commands
- scheduled learning maintenance LaunchAgent and `maintain-learning` command
- Depth 4 local OCR summary gate using macOS Apple Vision helper
- Tesseract CLI fallback for Depth 4 OCR summaries
- OCR provider posture in Product Doctor, Signal Depth, and Privacy payloads
