# Security And Privacy

This prototype is designed as a personal, consent-based attention sensor.

It collects:

- active application name
- active window title, unless disabled
- derived domain label
- timestamp and estimated dwell time
- low-detail system state events when ignored system apps are detected
- derived context graph nodes and edges from already-redacted event fields

It does not collect:

- keystrokes
- continuous screen recording or retained screenshot archives (opt-in OCR uses transient screenshots)
- clipboard contents
- microphone or camera input
- browser cookies
- intentional credential or token collection; pattern redaction is not a guarantee that every secret is caught

Sensitive titles are redacted by keyword before storage when `redact_sensitive_titles` is enabled.

PII masking is enabled by default before storage. The redactor masks emails, credit-card-like numbers that pass Luhn validation, US SSNs, phone numbers, IPv4 addresses, common secret/API token shapes, URL paths, and configured names.

The context graph is derived at read time from the redacted SQLite ledger. It does not store a second graph database. Sensitive findings become aggregate masked nodes such as `blocked card data` or `masked identity/contact`, and system-state samples are excluded from the work-context graph unless `context_graph_include_system_events` is enabled.

If you change `name_terms_to_mask` or other masking settings later, run `digital-twin-sensor redact-existing` to apply the new rules to previously stored rows.

Use this only on devices and accounts you own or where every monitored user has given informed consent. For workplace deployment, add policy controls before use: retention limits, user-visible status, opt-out, admin audit logs, encryption at rest, and clear data subject access/deletion procedures.

For a stronger privacy posture, set:

```json
{
  "capture_window_title": false,
  "redact_sensitive_titles": true
}
```

Data is stored locally by default:

```text
~/.digital-twin-sensor/events.sqlite
~/.digital-twin-sensor/config.json
```

The dashboard launched by `digital-twin-sensor ui` only accepts loopback bindings. APIs require a per-process session header and check Host/Origin. This is not enterprise authentication and does not protect against another process running as your user.

Optional encryption must be explicitly enabled with the encryption extra installed and `encrypt-store`; installing the extra alone does not enable it. Event text/metadata and learning-card text/feedback notes are encrypted. Timing, app, domain, subject/linkage identifiers, and feedback labels remain readable. Missing keys fail closed. Full purge removes local subject events, cached cards, and feedback; retention invalidates cached cards while preserving feedback restrictions. Exports and backups are not erased by database purge.

The Product Doctor and watchdog check operational metadata only: service state, process id, last exit code, sample freshness, configured privacy flags, database presence, OCR provider posture, and macOS permission posture. They do not inspect persisted screenshots, keystrokes, clipboard content, microphone input, camera input, cookies, credentials, or raw document bodies.

Depth 4 OCR is local-only and allowlist-gated. The macOS helper may create a temporary screenshot file long enough for Apple Vision or Tesseract OCR to read it, deletes that file immediately, and persists only redacted text hints, confidence, provider metadata, and redaction findings.

Collection can be paused without uninstalling the background service:

```bash
digital-twin-sensor pause
digital-twin-sensor resume
```

Local deletion is guarded. The CLI requires `--yes`, and the dashboard purge route requires a confirmation token:

```bash
digital-twin-sensor purge --older-than-days 30 --yes
digital-twin-sensor purge --all --yes
```
