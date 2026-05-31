#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/deploy/systemd"
TARGET_DIR="${HOME}/.config/systemd/user"
EXPECTED_ROOT="${HOME}/uav_project/uav_system-rk3588"
APP_PYTHON="${HOME}/anaconda3/envs/app/bin/python"
YOLO_PYTHON="${HOME}/anaconda3/envs/yolo/bin/python"

ENABLE_NOW=false
if [[ "${1:-}" == "--enable-now" ]]; then
  ENABLE_NOW=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--enable-now]" >&2
  exit 1
fi

if [[ "${REPO_ROOT}" != "${EXPECTED_ROOT}" ]]; then
  echo "Repository must be deployed at: ${EXPECTED_ROOT}" >&2
  echo "Current repository path:       ${REPO_ROOT}" >&2
  exit 1
fi

if [[ ! -x "${APP_PYTHON}" ]]; then
  echo "Missing app environment Python: ${APP_PYTHON}" >&2
  exit 1
fi

if [[ ! -x "${YOLO_PYTHON}" ]]; then
  echo "Missing YOLO environment Python: ${YOLO_PYTHON}" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"
cp "${SOURCE_DIR}/uav-app.service" "${SOURCE_DIR}/uav-yolo.service" "${TARGET_DIR}/"
systemctl --user daemon-reload

echo "Installed user services:"
echo "  ${TARGET_DIR}/uav-app.service"
echo "  ${TARGET_DIR}/uav-yolo.service"

if [[ "${ENABLE_NOW}" == true ]]; then
  systemctl --user enable --now uav-app.service uav-yolo.service
  echo "Enabled and started uav-app.service and uav-yolo.service."
else
  echo "Services were not started."
  echo "Enable them when ready:"
  echo "  systemctl --user enable --now uav-app.service uav-yolo.service"
fi

echo
echo "For startup without an interactive login, run once:"
echo "  sudo loginctl enable-linger \"${USER}\""
