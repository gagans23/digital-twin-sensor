# Enterprise Portability

This project now includes Fleet Manager Lite: a local-first control-plane model for turning one personal sensor into a managed endpoint fleet.

## Current State

Implemented locally:

- stable device id and device name in `config.json`
- local device health from collector and dashboard LaunchAgents
- watchdog LaunchAgent for scheduled self-heal checks
- product doctor CLI and `/api/health`
- active policy summary
- capture-surface connector inventory
- sync-readiness gates
- portability checklist
- context-pack export through the Memory Admission Gate
- pause/resume controls
- retention purge controls
- Fleet dashboard tab
- `/api/fleet`
- `/api/context-pack`
- `digital-twin-sensor fleet`
- `digital-twin-sensor doctor`
- `digital-twin-sensor watchdog --fix`
- `digital-twin-sensor pause`
- `digital-twin-sensor resume`
- `digital-twin-sensor purge --older-than-days N --yes`
- `digital-twin-sensor context-pack`

No raw event data is uploaded. There is no remote control plane yet.

## Target Architecture

```text
Endpoint Agent -> Local Redaction -> Local Graph/Spheres -> Product Doctor -> Summary Sync -> Control Plane -> Admin UI
```

The endpoint should remain useful when offline. A remote service should manage policy, enrollment, safe context-pack sync, and audit logs.

## Endpoint Requirements

Each computer should have:

- device identity
- signed installer
- background service
- watchdog/self-heal service
- visible collection status
- local config policy
- local encrypted store
- local redaction before persistence
- heartbeat reporting
- connector health reporting
- product doctor reporting
- local pause/resume controls
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
- watchdog health
- collector version
- policy version
- privacy-gate counts
- redacted working-sphere summaries
- redacted context graph summaries
- context packs approved for export
- pause/resume state
- retention expiry counts

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

## Implemented Export Layer

Context Pack Export now follows this local pipeline:

```text
Working Sphere -> Memory Admission Gate -> Redacted Markdown/JSON Pack -> Kiro/Codex/GitLab
```

This creates enterprise value before remote sync exists, because it lets the local twin hand off useful, governed context without exposing the raw database.

## Next Build

The next useful implementation step is a remote context-pack registry with explicit approval:

```text
Local Pack -> Approval -> Signed Summary Sync -> Context-Pack Registry -> Audit Log
```

Keep raw events local until encryption, signed installers, retention controls, and endpoint enrollment are implemented.

## Availability Model

Local availability now has four layers:

```text
Collector LaunchAgent -> Dashboard LaunchAgent -> Watchdog LaunchAgent -> Learning Maintenance LaunchAgent
```

The watchdog and learning maintenance jobs are scheduled rather than permanently running. A healthy macOS `launchctl print` may therefore show either one as `not running` with a recent zero exit code.
