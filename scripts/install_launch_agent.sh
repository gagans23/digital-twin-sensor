#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HOME}/.digital-twin-sensor"
VENV="${INSTALL_DIR}/venv"
PLIST="${HOME}/Library/LaunchAgents/com.local.digital-twin-sensor.plist"

mkdir -p "${INSTALL_DIR}" "${HOME}/Library/LaunchAgents"

python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip
"${VENV}/bin/pip" install --force-reinstall "${PROJECT_DIR}"
"${VENV}/bin/digital-twin-sensor" init

if command -v swiftc >/dev/null 2>&1; then
  swiftc "${PROJECT_DIR}/helpers/macos-window-probe.swift" -o "${INSTALL_DIR}/macos-window-probe" || true
  swiftc "${PROJECT_DIR}/helpers/macos-ocr-probe.swift" -o "${INSTALL_DIR}/macos-ocr-probe" || true
fi

sed \
  -e "s#__VENV_BIN__#${VENV}/bin#g" \
  -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
  -e "s#__HOME__#${HOME}#g" \
  "${PROJECT_DIR}/launchd/com.local.digital-twin-sensor.plist.template" \
  > "${PLIST}"

launchctl bootout "gui/$(id -u)" "${PLIST}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/com.local.digital-twin-sensor"

echo "Installed LaunchAgent: ${PLIST}"
echo "Logs: ${INSTALL_DIR}/sensor.log and ${INSTALL_DIR}/sensor.err.log"
echo "If collection fails, grant Accessibility permission to your terminal app or Python."
