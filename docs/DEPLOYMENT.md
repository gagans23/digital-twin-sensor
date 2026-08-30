# Deployment

This project currently targets a local macOS endpoint. It can be packaged for broader deployment, but raw remote sync should wait until the enterprise controls listed below exist.

## Local Developer Deployment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
digital-twin-sensor init
digital-twin-sensor ui
```

## Local Background Deployment

Install all LaunchAgents:

```bash
chmod +x scripts/install_launch_agent.sh scripts/install_dashboard_agent.sh scripts/install_watchdog_agent.sh scripts/install_learning_agent.sh
scripts/install_launch_agent.sh
scripts/install_dashboard_agent.sh
scripts/install_watchdog_agent.sh
scripts/install_learning_agent.sh
```

Verify:

```bash
digital-twin-sensor doctor
launchctl print gui/$(id -u)/com.local.digital-twin-sensor
launchctl print gui/$(id -u)/com.local.digital-twin-dashboard
launchctl print gui/$(id -u)/com.local.digital-twin-watchdog
launchctl print gui/$(id -u)/com.local.digital-twin-learning
```

Open:

```text
http://127.0.0.1:8765/
```

## Uninstall Services

```bash
scripts/uninstall_learning_agent.sh
scripts/uninstall_watchdog_agent.sh
scripts/uninstall_dashboard_agent.sh
scripts/uninstall_launch_agent.sh
```

Local data remains in:

```text
~/.digital-twin-sensor/
```

Delete data explicitly:

```bash
digital-twin-sensor purge --all --yes
```

## Logs

```bash
tail -f ~/.digital-twin-sensor/sensor.log
tail -f ~/.digital-twin-sensor/sensor.err.log
tail -f ~/.digital-twin-sensor/dashboard.log
tail -f ~/.digital-twin-sensor/dashboard.err.log
tail -f ~/.digital-twin-sensor/watchdog.log
tail -f ~/.digital-twin-sensor/watchdog.err.log
tail -f ~/.digital-twin-sensor/learning.log
tail -f ~/.digital-twin-sensor/learning.err.log
```

## Enterprise Readiness Checklist

Before deploying to managed workplace devices, add:

- signed macOS package
- MDM deployment profile
- visible menubar collection indicator
- central policy assignment
- SSO/OIDC/SAML
- role-based access control
- encryption at rest
- retention and deletion workflows
- audit logs
- endpoint enrollment and remote disable
- summary-only sync
- explicit consent/user notice
- data subject access/export/deletion procedures

## Recommended Enterprise Sync Boundary

Sync by default:

- device id
- device health
- agent version
- policy version
- watchdog status
- privacy-gate counts
- redacted working-sphere summaries
- approved context packs
- retention expiry counts

Do not sync by default:

- raw event rows
- raw URLs
- screenshots
- keystrokes
- clipboard
- microphone/camera data
- cookies
- credentials
- document bodies

## Packaging Roadmap

| Platform | Target |
| --- | --- |
| macOS | signed `.pkg`, LaunchAgent, optional MDM permission profile |
| Windows | signed `.msi`, Windows Service, Edge/Chrome metadata connector |
| Linux | `.deb`/`.rpm`, systemd user service |
| Enterprise service | context-pack registry, policy service, audit log, enrollment API |
