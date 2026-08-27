# Digital Twin Sensor Starter

This is a privacy-first local prototype inspired by the X-SYNTH paper, which argues that context synthesis should use observed digital human attention as a relevance signal rather than relying on query-only retrieval.

In this starter, the "sensor" is software. It samples your active macOS window, stores local attention events in SQLite, computes a rolling Digital Twin Signature, and ranks artifacts using attention filters plus simple content relevance.

## What It Implements

The paper describes a four-stage pipeline:

1. subject scoping
2. per-person attention modality selection
3. attention-and-content weighted retrieval
4. synthesis with modality annotations

This starter implements a single-user version:

- subject scoping: one local subject from `config.json`
- Digital Twin Signature: `v_dom`, `v_rhythm`, `v_base`, `v_resp`, `v_div`
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
- active-hour rhythm
- top apps and artifacts
- Digital Twin Signature radar view
- X-SYNTH-lite evidence search
- raw event ledger
- privacy ledger showing what is and is not collected

If you only want the URL and do not want the browser to open automatically:

```bash
digital-twin-sensor ui --no-open
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

Print your Digital Twin Signature:

```bash
digital-twin-sensor profile --short-days 5 --long-days 14
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
3. add browser/IDE/calendar connectors with opt-in toggles
4. add local embeddings for semantic content scoring
5. add a small local API for querying the twin
6. add feedback buttons so good/bad answers can tune filter selection
7. add a visible menubar indicator so collection is never hidden

## Product Design Notes

See `UI_RESEARCH_AND_DIRECTION.md` for the public Workfabric/ContextFabric references that shaped the dashboard and the ways this prototype intentionally improves transparency for a personal digital twin.

## Important Boundary

Do not use this to monitor other people without informed consent. The X-SYNTH idea becomes powerful exactly because attention traces are sensitive. Treat them like private behavioral data.
