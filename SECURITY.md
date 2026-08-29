# Security Policy

Digital Twin Sensor handles local activity metadata and derived context. Treat security and privacy issues as high priority.

## Supported Version

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting A Vulnerability

Do not open a public issue for vulnerabilities involving:

- sensitive data leakage
- redaction bypass
- raw event upload
- unauthorized dashboard/API access
- retention deletion failure
- unintended screenshot, keystroke, clipboard, microphone, camera, cookie, password, or token capture

Report privately to the project maintainer first.

## Security Expectations

- The dashboard binds to `127.0.0.1` by default.
- The API is not yet authenticated.
- Do not expose the dashboard to a public network.
- Do not deploy to other users' devices without explicit informed consent.
- Do not enable raw remote sync without encryption, authentication, role-based access, audit logs, retention controls, and consent workflows.

See [SECURITY_PRIVACY.md](SECURITY_PRIVACY.md) for the full privacy posture.
