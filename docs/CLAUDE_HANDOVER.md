# Claude Handover

This repository is the Digital Twin Sensor product prototype:

```text
https://github.com/gagans23/digital-twin-sensor
```

The goal is to turn personal digital-attention traces into a privacy-gated context graph and context packs that help coding agents resume work. It is inspired by X-SYNTH and adjacent context engineering / agent memory research, but it should not be described as a faithful copy of a person.

## Current Product State

Built and pushed:

- macOS active-window collector
- local SQLite event store
- pre-storage PII/secret redaction
- Digital Twin Signature vectors
- attention-weighted retrieval
- living context graph
- working spheres and resume packs
- Memory Admission Gate
- summary-only context packs for Kiro, Codex, GitLab, or local file
- local dashboard at `127.0.0.1:8765`
- Signal Depth, Privacy, Fleet, Product Ops, Context Pack, and Learning Mode UI
- Product Doctor and watchdog LaunchAgent
- scheduled learning-maintenance LaunchAgent
- local feedback labels for packs, spheres, and evidence
- evolving context cards
- Depth 2 browser tab metadata for Safari/Chrome
- Depth 3 allowlisted Accessibility metadata
- Depth 4 local OCR summary gate for allowlisted opaque apps
- macOS Apple Vision OCR helper with Tesseract CLI fallback

Important prior commits:

```text
216dcca Deduplicate OCR permission diagnostics
b46be96 Add local OCR summary gate
8932bfc Add scheduled learning maintenance
542c9d0 Add local learning mode
```

## Privacy Rules That Must Not Be Broken

Do not store:

- keystrokes
- clipboard contents
- microphone input
- camera frames
- persisted screenshots
- browser cookies
- passwords, tokens, secrets
- raw browser URL paths, queries, or fragments by default
- raw event uploads by default

OCR is allowed only as a local, explicit, allowlisted fallback at Depth 4. The helper may create a temporary screenshot file, runs local OCR, deletes the file immediately, and stores only redacted text hints, summary, confidence, provider name, and redaction findings.

## Architecture Map

Core files:

- `digital_twin_sensor/collectors/macos_active_window.py`: main collection path
- `digital_twin_sensor/collectors/browser_tab.py`: Safari/Chrome metadata
- `digital_twin_sensor/collectors/accessibility_surface.py`: Depth 3 UI labels
- `digital_twin_sensor/collectors/local_ocr.py`: Depth 4 OCR summary gate
- `helpers/macos-window-probe.swift`: active app/window helper
- `helpers/macos-ocr-probe.swift`: Apple Vision/Tesseract OCR helper
- `digital_twin_sensor/redaction.py`: PII/secret masking
- `digital_twin_sensor/store.py`: SQLite ledger
- `digital_twin_sensor/twin.py`: Digital Twin Signature
- `digital_twin_sensor/context_graph.py`: graph builder
- `digital_twin_sensor/working_spheres.py`: interrupted-work clustering
- `digital_twin_sensor/context_pack.py`: Memory Admission Gate and exports
- `digital_twin_sensor/learning.py`: feedback labels and context cards
- `digital_twin_sensor/health.py`: Product Doctor and research/product gaps
- `digital_twin_sensor/web.py`: local API and dashboard payloads
- `digital_twin_sensor/ui_static/`: dashboard HTML/CSS/JS

Pipeline:

```text
Collect -> Redact -> Store -> Signature -> Context Graph -> Working Spheres -> Admission Gate -> Context Pack -> Feedback Labels -> Context Cards
```

## Run And Validate

Local developer run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[encrypted]"
digital-twin-sensor init
digital-twin-sensor configure --depth 4 --ocr-surface-details on --ocr-app "Ibo Pro Player"
digital-twin-sensor ui
```

Background services:

```bash
scripts/install_launch_agent.sh
scripts/install_dashboard_agent.sh
scripts/install_watchdog_agent.sh
scripts/install_learning_agent.sh
digital-twin-sensor doctor
```

Tests:

```bash
python -m unittest discover -s tests
python -m compileall digital_twin_sensor
node --check digital_twin_sensor/ui_static/app.js
swiftc helpers/macos-ocr-probe.swift -o /tmp/macos-ocr-probe-test
git diff --check
```

Current expected suite size: 65 tests.

## Best Next Build

Build **Structured App Connectors v1** so OCR is used less often.

Priority adapters:

1. Ibo Pro Player connector
   - Goal: exact media title, module/lesson, playback state, timestamp, channel/course if exposed.
   - Preferred source order: native app API if any, Accessibility labels, OCR fallback.
   - Store: title/module/timestamp/state summary only, redacted.

2. Git/Kiro/Codex work connector
   - Goal: current repo, branch, changed-file count, active task/artifact.
   - Store: repo name, branch, relative file names, diff stats, no source file bodies by default.

3. Browser page semantics connector
   - Goal: page title, domain, canonical page type, top headings for allowlisted domains.
   - Store: title/domain/headings only; URL path/query remains off by default unless explicitly enabled.

4. Evaluation harness
   - Add task-resume experiments measuring useful evidence rate, stale evidence rate, privacy leak rate, and time to resume.
   - Use labels from `context_feedback` as the first dataset.

## Paper Framing

Use this claim:

```text
Device-native attention traces can improve agent handoff when transformed into privacy-gated context graphs, working spheres, and summary-only context packs.
```

Do not claim:

- the system is a complete human digital twin
- attention proves causality
- the router is learned like X-SYNTH
- OCR sees everything inside apps
- raw data is needed for useful context

## Claude Prompt

```text
You are helping continue the Digital Twin Sensor repo at https://github.com/gagans23/digital-twin-sensor.

Read README.md, SECURITY_PRIVACY.md, docs/UNDER_THE_HOOD.md, docs/RESEARCH_AND_EVALUATION.md, and docs/CLAUDE_HANDOVER.md first.

Your job is to build Structured App Connectors v1 without weakening privacy. Start with Ibo Pro Player, then Git/Kiro/Codex context, then browser page semantics. Preserve the collection-depth model:

Depth 1 = active app/title/dwell
Depth 2 = browser tab title/domain
Depth 3 = allowlisted Accessibility labels
Depth 4 = local OCR summaries only when structured metadata is empty

Never store keystrokes, clipboard, microphone, camera, persisted screenshots, cookies, credentials, or raw URL paths/queries by default. Add tests, update docs, run the full validation suite, and keep the dashboard clear about what was collected, masked, denied, and inferred.
```
