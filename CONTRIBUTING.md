# Contributing

Digital Twin Sensor is intentionally privacy-first. Contributions should improve usefulness without weakening user control.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m unittest discover -s tests
```

## Contribution Principles

- Prefer metadata and summaries over raw content.
- Redact before storage.
- Keep new sensors opt-in and visible in the dashboard.
- Add tests for privacy boundaries and failure behavior.
- Avoid adding third-party runtime dependencies unless they remove real complexity.
- Do not add cloud upload of raw events as a default.

## Pull Request Checklist

- Tests pass with `python3 -m unittest discover -s tests`.
- Python compiles with `python3 -m compileall digital_twin_sensor`.
- UI JavaScript passes `node --check digital_twin_sensor/ui_static/app.js` when Node is available.
- New collection surfaces are documented in `COLLECTION_DEPTH_AND_REDACTION.md`.
- New exports pass through the Memory Admission Gate.
- User-facing docs are updated.
