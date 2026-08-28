# Enterprise Portability

This project now includes Fleet Manager Lite: a local-first control-plane model for turning one personal sensor into a managed endpoint fleet.

## Current State

Implemented locally:

- stable device id and device name in `config.json`
- local device health from collector and dashboard LaunchAgents
- active policy summary
- capture-surface connector inventory
- sync-readiness gates
- portability checklist
- Fleet dashboard tab
- `/api/fleet`
- `digital-twin-sensor fleet`

No raw event data is uploaded. There is no remote control plane yet.

## Target Architecture

```text
Endpoint Agent -> Local Redaction -> Local Graph/Spheres -> Summary Sync -> Control Plane -> Admin UI
```

The endpoint should remain useful when offline. A remote service should manage policy, enrollment, safe context-pack sync, and audit logs.

## Endpoint Requirements

Each computer should have:

- device identity
- signed installer
- background service
- visible collection status
- local config policy
- local encrypted store
- local redaction before persistence
- heartbeat reporting
- connector health reporting
- local pause/resume
- local delete/export controls

## Control Plane Requirements

The enterprise service should manage:

- device enrollment
- policy assignment
- user/admin roles
- SSO/OIDC/SAML
- fleet heartbeat view
- connector inventory
- summary-only sync
- audit log
- context pack registry
- retention and deletion policies
- remote disable/wipe

## Sync Policy

Default sync should be summary-only:

- device health
- collector version
- policy version
- privacy-gate counts
- redacted working-sphere summaries
- redacted context graph summaries
- context packs approved for export

Do not sync by default:

- raw event ledger
- raw URLs
- screenshots
- keystrokes
- clipboard
- microphone/camera data
- credentials, tokens, or secrets

## Portable Packaging

Recommended targets:

- macOS: signed `.pkg`, LaunchAgent/Daemon, MDM profile for Accessibility permission
- Windows: signed `.msi`, Windows Service, Edge/Chrome connector
- Linux: `.deb`/`.rpm`, systemd user service
- Docker: control plane and development demo

## Next Build

The next useful implementation step is Context Pack Export:

```text
Working Sphere -> Memory Admission Gate -> Redacted Markdown/JSON Pack -> Kiro/Codex/GitLab
```

This creates enterprise value before remote sync exists, because it lets the local twin hand off useful, governed context without exposing the raw database.
