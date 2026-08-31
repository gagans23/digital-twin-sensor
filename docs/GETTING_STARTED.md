# Getting Started

This guide installs Digital Twin Sensor locally and launches the dashboard.

## Requirements

- macOS for live foreground-window collection
- Python 3.9 or newer
- Git
- Optional: Swift compiler for the native macOS window probe

The core package has no third-party Python runtime dependencies.

## Install From Source

```bash
git clone <your-gitlab-repo-url>
cd digital-twin-sensor-starter
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
digital-twin-sensor init
```

## Run A First Sample

```bash
digital-twin-sensor collect-once
digital-twin-sensor profile
digital-twin-sensor query "what have I been focused on today?"
```

## Launch The Dashboard

```bash
digital-twin-sensor ui
```

Open:

```text
http://127.0.0.1:8765/
```

Do not open `digital_twin_sensor/ui_static/index.html` directly for normal use. The static file cannot call the local API correctly without the dashboard server.

## macOS Permission

The active-window collector needs macOS Accessibility permission for the terminal app or Python runtime that runs it.

Open:

```text
System Settings -> Privacy & Security -> Accessibility
```

Enable your terminal app. If Depth 2 or Depth 3 app-specific metadata is enabled, macOS may also ask for Automation permission the first time the sensor inspects Safari, Chrome, or an allowlisted app.

## Run Continuously

```bash
digital-twin-sensor run --interval 15 --verbose
```

Stop with `Ctrl-C`.

## Install Background Services

```bash
chmod +x scripts/install_launch_agent.sh scripts/install_dashboard_agent.sh scripts/install_watchdog_agent.sh scripts/install_learning_agent.sh
scripts/install_launch_agent.sh
scripts/install_dashboard_agent.sh
scripts/install_watchdog_agent.sh
scripts/install_learning_agent.sh
```

This installs:

- collector LaunchAgent
- dashboard LaunchAgent
- scheduled watchdog LaunchAgent
- scheduled learning-maintenance LaunchAgent

Check health:

```bash
digital-twin-sensor doctor
```

## Pause, Resume, And Purge

Pause collection without uninstalling services:

```bash
digital-twin-sensor pause
```

Resume collection:

```bash
digital-twin-sensor resume
```

Delete rows older than a retention threshold:

```bash
digital-twin-sensor purge --older-than-days 30 --yes
```

Reset the local event ledger:

```bash
digital-twin-sensor purge --all --yes
```

## Enable Deeper Context Safely

Depth 2 browser metadata:

```bash
digital-twin-sensor configure --depth 2 --browser-tab-details on --browser-url-path off --browser-url-query off
```

Depth 3 allowlisted Accessibility metadata:

```bash
digital-twin-sensor configure --depth 3 --accessibility-surface-details on --accessibility-app "Ibo Pro Player"
```

Depth 4 local OCR summaries for an opaque allowlisted app:

```bash
digital-twin-sensor configure --depth 4 --ocr-surface-details on --ocr-app "Ibo Pro Player" --ocr-max-lines 12 --ocr-min-confidence 0.35
```

On macOS, Depth 4 uses the helper installed by `scripts/install_launch_agent.sh`. It prefers Apple Vision and can fall back to Tesseract when the CLI is installed. macOS may require Screen Recording permission for the terminal or Python runtime. The product stores redacted OCR hints and summary only, not screenshots.

Optional Tesseract fallback:

```bash
brew install tesseract
digital-twin-sensor configure --ocr-provider tesseract --ocr-tesseract-binary "$(command -v tesseract)"
```

## Export A Context Pack

For Kiro:

```bash
digital-twin-sensor context-pack --days 14 --target kiro --format markdown
```

For GitLab-safe issue/handoff text:

```bash
digital-twin-sensor context-pack --days 14 --target gitlab --purpose gitlab --output work/context-pack.md
```

Context packs are summary-only by design. They do not include raw event rows, subject identity, screenshots, keystrokes, clipboard content, document bodies, passwords, or raw URL paths/queries.
