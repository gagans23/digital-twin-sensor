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
- screenshots
- clipboard contents
- microphone or camera input
- browser cookies
- passwords or tokens

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

The dashboard launched by `digital-twin-sensor ui` binds to `127.0.0.1` by default, so it is intended for local inspection on your machine. Do not expose it on a public network unless you first add authentication, transport security, retention controls, and explicit consent workflows.

The Product Doctor and watchdog check operational metadata only: service state, process id, last exit code, sample freshness, configured privacy flags, database presence, and macOS permission posture. They do not inspect screenshots, keystrokes, clipboard content, microphone input, camera input, cookies, credentials, or raw document bodies.

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
