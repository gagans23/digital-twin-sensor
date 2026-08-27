#!/usr/bin/env bash
set -euo pipefail

PLIST="${HOME}/Library/LaunchAgents/com.local.digital-twin-sensor.plist"

launchctl bootout "gui/$(id -u)" "${PLIST}" >/dev/null 2>&1 || true
rm -f "${PLIST}"

echo "Removed LaunchAgent. Data remains in ${HOME}/.digital-twin-sensor."
