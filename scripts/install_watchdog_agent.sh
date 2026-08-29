#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HOME}/.digital-twin-sensor"
VENV="${INSTALL_DIR}/venv"
PLIST="${HOME}/Library/LaunchAgents/com.local.digital-twin-watchdog.plist"

mkdir -p "${INSTALL_DIR}" "${HOME}/Library/LaunchAgents"

python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip
"${VENV}/bin/pip" install --force-reinstall "${PROJECT_DIR}"

sed \
  -e "s#__VENV_BIN__#${VENV}/bin#g" \
  -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
  -e "s#__HOME__#${HOME}#g" \
  "${PROJECT_DIR}/launchd/com.local.digital-twin-watchdog.plist.template" \
  > "${PLIST}"

launchctl bootout "gui/$(id -u)" "${PLIST}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/com.local.digital-twin-watchdog"

echo "Installed Watchdog LaunchAgent: ${PLIST}"
echo "Logs: ${INSTALL_DIR}/watchdog.log and ${INSTALL_DIR}/watchdog.err.log"
