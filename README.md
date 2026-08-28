# Digital Twin Sensor Starter

This is a privacy-first local prototype inspired by the X-SYNTH paper, which argues that context synthesis should use observed digital human attention as a relevance signal rather than relying on query-only retrieval.

In this starter, the "sensor" is software. It samples your active macOS window, stores local attention events in SQLite, computes a rolling Digital Twin Signature, builds a living context graph with privacy gates, infers working spheres from redacted focus patterns, and ranks artifacts using attention filters plus simple content relevance.

If macOS only reports a locked or hidden user session such as `loginwindow`, the sensor records a low-detail `system` event. That keeps collection health visible without claiming it captured the foreground app.

PII masking is enabled by default before data is written to SQLite. It masks emails, credit-card-like numbers validated with Luhn, SSNs, phone numbers, IP addresses, common secret/token shapes, URL paths, and configured names.

At Depth 2, configured browsers such as Safari and Google Chrome can also record active-tab metadata: redacted tab title, URL domain, sanitized URL, and URL path/query policy. Raw browser paths, queries, fragments, usernames, and passwords are not stored by default.

## What It Implements

The paper describes a four-stage pipeline:

1. subject scoping
2. per-person attention modality selection
3. attention-and-content weighted retrieval
4. synthesis with modality annotations

This starter implements a single-user version:

- subject scoping: one local subject from `config.json`
- Digital Twin Signature: `v_dom`, `v_rhythm`, `v_base`, `v_resp`, `v_div`
- context graph: subject, domain, app, artifact, task, time, and masked private-signal nodes
- working spheres: inferred activities, session returns, transition paths, and resume packs
- browser surface details: active-tab metadata for Safari/Chrome at Depth 2+
- privacy gates: capture depth, pre-storage redaction, graph minimization, and sensitive-source boundaries
- filters: proportional, inverse, differential, recurrent, comparative, sequential, collective
- retrieval: `weight = attention_score * content_score`
- synthesis: text output explaining why each artifact was surfaced

## Quick Start

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
digital-twin-sensor init
digital-twin-sensor collect-once
digital-twin-sensor profile
digital-twin-sensor query "what have I been focused on today?"
```

## Local UI

Launch the visual dashboard:

```bash
digital-twin-sensor ui
```

It opens a local-only browser console with:

- collection health
- attention by domain
- working spheres and resume packs
- surface detail cards explaining what each app exposes and how to deepen capture
- fleet manager for local device health, policy, connectors, and sync-readiness
- active-hour rhythm
- top apps and artifacts
- privacy-gated context graph
- Digital Twin Signature radar view
- X-SYNTH-lite evidence search
- raw event ledger
- privacy ledger showing what is and is not collected

If you only want the URL and do not want the browser to open automatically:

```bash
digital-twin-sensor ui --no-open
```

To keep the dashboard available at login:

```bash
chmod +x scripts/install_dashboard_agent.sh scripts/uninstall_dashboard_agent.sh
scripts/install_dashboard_agent.sh
```

For live collection:

```bash
digital-twin-sensor run --interval 15 --verbose
```

Stop with `Ctrl-C`.

## macOS Permission

The active-window collector uses AppleScript via `osascript`. macOS may require Accessibility permission for your terminal app.

Open:

```text
System Settings -> Privacy & Security -> Accessibility
```

Then enable the terminal app you are using.

## Deploy As A Background Sensor

Run:

```bash
chmod +x scripts/install_launch_agent.sh scripts/uninstall_launch_agent.sh
scripts/install_launch_agent.sh
```

This installs a user LaunchAgent that starts the sensor at login.
On macOS, the installer also tries to compile a tiny native window probe at `~/.digital-twin-sensor/macos-window-probe`; if that is unavailable, collection falls back to AppleScript.

Check logs:

```bash
tail -f ~/.digital-twin-sensor/sensor.log
tail -f ~/.digital-twin-sensor/sensor.err.log
```

Uninstall the background agent:

```bash
scripts/uninstall_launch_agent.sh
```

Your local data remains in `~/.digital-twin-sensor`.

## Useful Commands

Collect one sample:

```bash
digital-twin-sensor collect-once
```

Run continuously:

```bash
digital-twin-sensor run --interval 15
```

Enable Depth 2 browser-tab metadata:

```bash
digital-twin-sensor configure --depth 2 --browser-tab-details on --browser-url-path off --browser-url-query off
```

Print your Digital Twin Signature:

```bash
digital-twin-sensor profile --short-days 5 --long-days 14
```

Build the living context graph:

```bash
digital-twin-sensor graph --days 14
```

Infer working spheres and resume packs:

```bash
digital-twin-sensor activities --days 14
```

Show local fleet/device management status:

```bash
digital-twin-sensor fleet --days 14
```

Ask a query:

```bash
digital-twin-sensor query "what work changed this week?"
digital-twin-sensor query "what did I repeatedly come back to?"
digital-twin-sensor query "what important area am I neglecting?"
```

Export recent raw events:

```bash
digital-twin-sensor export --days 7 > events.json
```

Re-apply masking to already stored events after changing redaction rules:

```bash
digital-twin-sensor redact-existing --dry-run
digital-twin-sensor redact-existing
```

Run the redaction tests:

```bash
python3 -m unittest discover -s tests
```

## How To Use This With Kiro

Open this folder in a fresh terminal and run:

```bash
kiro-cli chat
```

Good first prompts:

```text
Read this project and create .kiro/steering files for architecture, privacy constraints, and next development tasks.
```

```text
Turn this prototype into a spec for a production personal digital twin sensor. Include requirements, design, tasks, and privacy safeguards.
```

```text
Add a browser-history connector that stores only URL domain and page title, with a config flag and retention policy.
```

## Production Roadmap

Next build steps:

1. add explicit retention and deletion commands
2. encrypt the SQLite database
3. add IDE/calendar connectors with opt-in toggles
4. add per-app Accessibility detail for opaque apps such as media players
5. add local OCR summaries for explicitly allowlisted apps without storing screenshots
6. grow working spheres into task models with objectives, steps, and blockers
7. add graph-backed project/task clustering
8. add local embeddings for semantic content scoring
9. add a small local API for querying the twin
10. add feedback buttons so good/bad answers can tune filter selection
11. add a visible menubar indicator so collection is never hidden

## Product Design Notes

See `UI_RESEARCH_AND_DIRECTION.md` for the public Workfabric/ContextFabric references that shaped the dashboard and the ways this prototype intentionally improves transparency for a personal digital twin.

See `COLLECTION_DEPTH_AND_REDACTION.md` for the collection-depth model and masking policy.

See `RELATED_CONTEXT_PAPERS.md` for adjacent research papers and concrete product concepts such as working spheres, task-model induction, resume packs, seen indexes, evolving context cards, and query-time memory admission gates.

See `ENTERPRISE_PORTABILITY.md` for the fleet-management architecture, endpoint packaging path, and summary-only sync model.

## Important Boundary

Do not use this to monitor other people without informed consent. The X-SYNTH idea becomes powerful exactly because attention traces are sensitive. Treat them like private behavioral data.
