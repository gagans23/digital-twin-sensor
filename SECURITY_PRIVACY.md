# Security And Privacy

This prototype is designed as a personal, consent-based attention sensor.

It collects:

- active application name
- active window title, unless disabled
- derived domain label
- timestamp and estimated dwell time
- low-detail system state events when ignored system apps are detected

It does not collect:

- keystrokes
- screenshots
- clipboard contents
- microphone or camera input
- browser cookies
- passwords or tokens

Sensitive titles are redacted by keyword before storage when `redact_sensitive_titles` is enabled.

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
